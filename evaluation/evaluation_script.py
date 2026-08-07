from rag_app.db.engine import make_engine, make_sessionmaker
from rag_app.config import get_settings
from contextlib import asynccontextmanager
from rag_app.services.ingestor import IngestionService
from rag_app.services.retriever import RetrievalService
from rag_app.stores.chunk_store import ChunkStore
from rag_app.stores.pg_vector_store import PgVectorStore
from rag_app.stores.document_store import DocStore
from rag_app.embeddings import Embedder
from rag_app.chunkings.factory import build_chunker
from rag_app.chunkings.chunker import Chunker
from rag_app.api._helpers import _get_new_token, _hash_token
from sqlalchemy import text, delete
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncEngine
from uuid import UUID, uuid4
from dataclasses import dataclass
from rag_app.schemas import DocumentDTO
from rag_app.models import Document
from collections import defaultdict
from statistics import fmean
import json
import re
from rag_app.eval.metrics import recall, precision, reciprocal_rank, Span
from pathlib import Path
from asyncio import run
from hashlib import sha256

K_VALUES = [2, 4, 6, 8, 10]
CHUNK_SIZES = [64, 128, 192, 254]

CORPUS_ROOT = Path(__file__).parent / "corpus" / "fastapi-docs"
# Fixed print order so successive runs diff cleanly. "unanswerable" is absent on purpose: it is
# filtered out before the sweep (no gold spans -> no retrieval signal).
TIER_ORDER = [
    "lexical",
    "paraphrase",
    "vocabulary-shift",
    "needle",
    "multi-hop",
    "distractor",
]
METRICS = ["recall", "precision", "mrr", "chars"]


@dataclass(frozen=True)
class Identity:
    """A test tenant: the owner_id RLS scopes on, plus the raw (unhashed) session
    token -- usable as the `session_token` cookie value if HTTP tests are added
    later. `username`/`password` are set only for logged-in identities."""

    owner_id: UUID
    token: str
    username: str | None = None
    password: str | None = None


@dataclass(frozen=True)
class Rig:
    chunker: Chunker
    ingestor: IngestionService
    retriever: RetrievalService


@dataclass(frozen=True)
class Lifespan:
    engine: AsyncEngine
    session_maker: async_sessionmaker
    embedder: Embedder
    vec_store: PgVectorStore
    chunk_store: ChunkStore
    doc_store: DocStore
    services: dict
    tenants: dict


@asynccontextmanager
async def setup():
    engine = make_engine(get_settings().test_app_sqlalchemy_url)
    session_maker = make_sessionmaker(engine)
    embedder = Embedder()
    chunk_store = ChunkStore()
    doc_store = DocStore()
    vec_store = PgVectorStore()
    services = {}
    tenants = {}
    for ch_size in CHUNK_SIZES:
        cfg = get_settings().model_copy(update={"chunk_size": ch_size})
        chunker = build_chunker(embedder, cfg)
        services[ch_size] = Rig(
            chunker,
            IngestionService(doc_store, chunk_store, vec_store, embedder, chunker),
            RetrievalService(chunk_store, vec_store, doc_store, embedder, chunker),
        )
        anonym = await make_anonymous_tenant(session_maker)
        tenants[ch_size] = anonym.owner_id
    lifespan = Lifespan(
        engine=engine,
        session_maker=session_maker,
        embedder=embedder,
        vec_store=vec_store,
        chunk_store=chunk_store,
        doc_store=doc_store,
        services=services,
        tenants=tenants,
    )
    yield lifespan
    await lifespan.engine.dispose()


@asynccontextmanager
async def app_session(session_maker: async_sessionmaker, owner_id: UUID | None = None):
    async with session_maker.begin() as s:
        if owner_id is not None:
            await s.execute(
                text("SELECT set_config('app.owner_id', :id, true)"),
                {"id": str(owner_id)},
            )
        yield s


async def make_anonymous_tenant(session_maker: async_sessionmaker):
    token = _get_new_token()
    async with app_session(session_maker) as s:
        res = await s.execute(
            text("SELECT public.anonymous_mint(:token_hash)"),
            {"token_hash": _hash_token(token)},
        )
        owner_id = res.scalar_one()
    return Identity(owner_id=owner_id, token=token)


async def process_corpus(
    lifespan: Lifespan, documents: list[DocumentDTO], ch_size: int
):
    async with app_session(lifespan.session_maker, lifespan.tenants[ch_size]) as s:
        for doc in documents:
            await lifespan.services[ch_size].ingestor.store_document(s, doc)


async def cleanup(lifespan: Lifespan):
    # documents is FORCE RLS under the owner_isolation policy, which compares owner_id against
    # current_setting('app.owner_id'). An unscoped session leaves that unset, so the predicate is
    # NULL, the DELETE matches zero rows and succeeds silently. Scope one delete per tenant.
    for owner_id in lifespan.tenants.values():
        async with app_session(lifespan.session_maker, owner_id) as s:
            await s.execute(delete(Document).where(Document.owner_id == owner_id))


class GoldenError(Exception):
    """A golden quote did not resolve to exactly one well-formed span."""


_WORD = re.compile(r"\w")


def _find_all(haystack: str, needle: str) -> list[int]:
    """Every start index of `needle`, overlapping matches included -- counting conservatively
    means an ambiguous quote fails louder, never quieter."""
    out, i = [], haystack.find(needle)
    while i != -1:
        out.append(i)
        i = haystack.find(needle, i + 1)
    return out


def _is_word_boundary(text: str, start: int, end: int) -> bool:
    """A truncated quote is still a legal substring: it resolves silently and shifts every offset
    after it. Requiring both ends to sit on a word boundary is what catches that."""
    if start > 0 and _WORD.match(text[start - 1]) and _WORD.match(text[start]):
        return False
    if end < len(text) and _WORD.match(text[end - 1]) and _WORD.match(text[end]):
        return False
    return True


def _resolve_answer(qid: str, ans: dict, corpus_text: dict[str, str]) -> Span:
    doc = ans["document"]
    if doc not in corpus_text:
        raise GoldenError(f"{qid}: no corpus file named {doc!r}")
    content, quote = corpus_text[doc], ans["quote"]

    # `occurrence` is the expected *total* match count, not an index: the author asserts how many
    # times the quote appears, and a disagreement is a data bug, not a reason to take the first hit.
    matches = _find_all(content, quote)
    if len(matches) != ans["occurrence"]:
        raise GoldenError(
            f"{qid}: quote matched {len(matches)}x in {doc!r}, expected "
            f"{ans['occurrence']}: {quote[:60]!r}"
        )
    start = matches[-1]
    end = start + len(quote)
    if not _is_word_boundary(content, start, end):
        raise GoldenError(
            f"{qid}: quote starts or ends mid-word in {doc!r} -- truncated? {quote[:60]!r}"
        )
    return Span(doc, start, end)


def get_golds(corpus_text: dict[str, str]) -> list[dict]:
    """Load the goldens and resolve every quote to a Span. Quote-anchored on disk, offset-anchored
    in memory: the offsets index the same document.content string the chunker is handed, so they
    are directly comparable to chunk.offset_start/offset_end."""
    ret = []
    with open(Path(__file__).parent / "goldens.jsonl") as f:
        for line in f:
            g = json.loads(line)
            ret.append(
                {
                    "id": g["id"],
                    "tier": g["tier"],
                    "query": g["query"],
                    "answers": [
                        _resolve_answer(g["id"], a, corpus_text) for a in g["answers"]
                    ],
                }
            )
    return ret


def get_corpus() -> list[DocumentDTO]:
    docs = []
    for p in CORPUS_ROOT.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in [".md", ".txt"]:
            continue
        raw = p.read_bytes()
        # filename is the join key against a golden's "document" field, so it has to be the
        # corpus-relative path: index.md / middleware.md / websockets.md each exist several times.
        filename = p.relative_to(CORPUS_ROOT).as_posix()
        docs.append(
            DocumentDTO(
                id=uuid4(),
                filename=filename,
                content_hash=sha256(raw).hexdigest(),
                content=raw.decode("utf-8"),
                owner_id=uuid4(),
            )
        )
    return docs


def report(results: list[dict]) -> None:
    grouped, qids = defaultdict(list), defaultdict(set)
    for r in results:
        grouped[(r["tier"], r["chunk_size"], r["k"])].append(r)
        qids[r["tier"]].add(r["qid"])

    header = "".join(f"{'k=' + str(k):>7}" for k in K_VALUES)
    for tier in TIER_ORDER:
        if tier not in qids:
            continue
        print(f"\n=== {tier}  (n={len(qids[tier])} queries) ===")
        for metric in METRICS:
            print(f"{metric:<14}{header}")
            for ch_size in CHUNK_SIZES:
                cells = ""
                for k in K_VALUES:
                    rows = grouped[(tier, ch_size, k)]
                    if not rows:
                        cells += f"{'-':>7}"
                        continue
                    mean = fmean(r[metric] for r in rows)
                    cells += f"{mean:>7.0f}" if metric == "chars" else f"{mean:>7.2f}"
                print(f"  chunk {ch_size:>4}  {cells}")
    print(
        "\nNo cross-tier total by design: lexical saturates near 1.0 and multi-hop is capped at 0.5"
        "\nwhen one hop of two is retrieved, so a single mean hides the effect the sweep measures."
    )


async def main():
    documents = get_corpus()
    # Resolve the goldens before setup(): a bad quote should fail in a second, not after ingesting
    # the whole corpus at five chunk sizes.
    golds = [
        g
        for g in get_golds({d.filename: d.content for d in documents})
        if g["tier"] != "unanswerable"
    ]
    results = []
    async with setup() as lifespan:
        for ch_size in lifespan.services.keys():
            await process_corpus(
                lifespan,
                [
                    DocumentDTO(
                        uuid4(),
                        d.filename,
                        d.content_hash,
                        d.content,
                        lifespan.tenants[ch_size],
                    )
                    for d in documents
                ],
                ch_size,
            )
        for g in golds:
            for ch_size in CHUNK_SIZES:
                async with app_session(
                    lifespan.session_maker, lifespan.tenants[ch_size]
                ) as s:
                    res = await lifespan.services[ch_size].retriever.search_topk_chunks(
                        s, g["query"], max(K_VALUES), get_settings().retrieval_threshold
                    )
                    for k in K_VALUES:
                        k_res = res[:k]
                        spans = [
                            Span(doc_name, chunk.offset_start, chunk.offset_end)
                            for chunk, doc_name in k_res
                        ]
                        results.append(
                            {
                                "chunk_size": ch_size,
                                "tier": g["tier"],
                                "qid": g["id"],
                                "k": k,
                                "recall": recall(g["answers"], spans, tau=0.5),
                                "precision": precision(g["answers"], spans),
                                "mrr": reciprocal_rank(g["answers"], spans),
                                "chars": sum(s.char_end - s.char_start for s in spans),
                            }
                        )
        await cleanup(lifespan)
    report(results)


if __name__ == "__main__":
    run(main())
