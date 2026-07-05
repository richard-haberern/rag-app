"""Test doubles for the three external seams: tokenizer, embedder, LLM API.

All deterministic, no network, no model load. These are generic stand-ins for
`transformers` / `sentence-transformers` / the Gemini HTTP API"""

import hashlib
import re

import httpx

from rag_app.llm.llm_client import LLMClient
from rag_app.schemas import Embedding


class FakeTokenizer:
    """Stand-in for a HuggingFace *fast* tokenizer, with only what Chunker and
    Embedder.max_content_tokens touch.

    Tokenization scheme: one token per whitespace-delimited run; each token's
    offset is its (char_start, char_end) span in the original text. So
    "w01 w02 ... w40" -> 40 tokens, one per word, which lets a test count
    windows/overlap by eye. Empty / whitespace-only text -> no tokens, so
    offset_mapping is [] (and Chunker.chunk_text returns []).

    Like a real HF tokenizer, `input_ids` is always present; `offset_mapping`
    only when explicitly requested. Chunker reads offset_mapping;
    RetrievalService.search_topk_chunks reads input_ids for its length check.
    """

    # Chunker rejects slow tokenizers up front (return_offsets_mapping needs a fast one).
    is_fast = True

    def __call__(
        self,
        text: str,
        return_offsets_mapping: bool = False,
        add_special_tokens: bool = False,
    ) -> dict[str, list]:
        spans = [(m.start(), m.end()) for m in re.finditer(r"\S+", text)]
        out: dict[str, list] = {"input_ids": list(range(len(spans)))}
        if return_offsets_mapping:
            out["offset_mapping"] = spans
        return out

    def num_special_tokens_to_add(self, pair: bool = False) -> int:
        # Mirrors a BERT-style tokenizer ([CLS] + [SEP]); only here for fidelity,
        # FakeEmbedder reports max_content_tokens directly.
        return 2


class FakeEmbedder:
    """Duck-typed mirror of Embedder's public seam (tokenizer, max_content_tokens,
    dimension, embed_document, embed_query). Does NOT load SentenceTransformer.

    Vector scheme: sha256(text) bytes mapped to `dim` floats in [0, 1). Stable
    across runs (unlike salted hash()), so identical text -> identical vector
    (preserves ingest/query symmetry) and distinct texts -> distinct vectors.
    """

    def __init__(
        self, tokenizer: FakeTokenizer, dim: int = 8, max_content_tokens: int = 512
    ) -> None:
        self._tokenizer = tokenizer
        self._dim = dim
        self._max_content_tokens = max_content_tokens

    @property
    def tokenizer(self) -> FakeTokenizer:
        return self._tokenizer

    @property
    def max_content_tokens(self) -> int:
        return self._max_content_tokens

    @property
    def dimension(self) -> int:
        return self._dim

    def _vector(self, text: str) -> Embedding:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        return [digest[i % len(digest)] / 255.0 for i in range(self._dim)]

    def embed_document(self, texts: list[str]) -> list[Embedding]:
        return [self._vector(t) for t in texts]

    def embed_query(self, query: str) -> list[Embedding]:
        # Single-element outer list, matching the real Embedder's agreed return shape.
        return [self._vector(query)]


# --- Fake LLM API (httpx MockTransport) -------------------------------------
# Helpers produce Gemini-shaped JSON; a MockTransport handler returns them so the
# *real* LLMClient.generate / _extract_text run against canned responses. The
# AsyncClient lifecycle is owned by the `make_llm_client` conftest fixture.


def gemini_response(text: str) -> dict:
    """Success-shaped generateContent body carrying `text`."""
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


def gemini_blocked() -> dict:
    """200 with no usable candidate (safety block / empty) — should trip
    LLMClient._extract_text into its RuntimeError."""
    return {"candidates": []}


def make_mock_llm_client(handler) -> tuple[httpx.AsyncClient, LLMClient]:
    """Wire a MockTransport `handler` into a real LLMClient. Returns the client too
    so the caller can close it. The conftest `make_llm_client` fixture wraps this
    and handles teardown."""
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return client, LLMClient(model="fake", base_url="http://test", client=client)
