import pytest
import httpx
from uuid import uuid4
from rag_app.schemas import DocumentDTO, ChunkDTO
from rag_app.embeddings import Embedder
from rag_app.services.answerer import AnswerService
from rag_app.services.retriever import RetrievalService
from sqlalchemy.ext.asyncio import async_sessionmaker
from rag_app.chunkings.chunker import Chunker

from rag_app.exceptions import LLMBadAnswer
from tests.fakes import gemini_blocked, gemini_response


def make_handler(body: dict, status: int = 200):
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=body)

    return handler


async def test_blocked_response_raises(make_llm_client):
    # A 200 with no usable candidate (safety block / empty) must surface as the legible
    # RuntimeError that LLMClient._extract_text re-raises, not the raw KeyError/IndexError.
    llm = make_llm_client(make_handler(gemini_blocked()))
    with pytest.raises(LLMBadAnswer):
        await llm.generate("...")


async def test_correct_answer(make_llm_client):
    body = gemini_response("Generated correct output for the given input")
    llm = make_llm_client(make_handler(body))
    resp = await llm.generate("What is the main idea behind C++?")
    assert resp == "Generated correct output for the given input"


async def test_e2e(
    make_llm_client,
    pg_vector_store,
    doc_store,
    chunk_store,
    engine,
    session,
    new_session,
    db_tests,
    settings,
    tmp_path,
):
    f = tmp_path / "doc.txt"
    f.write_text("Some real content with words in it")
    embedder = Embedder()
    chunker = Chunker(
        embedder.tokenizer,
        embedder.max_content_tokens,
        round(embedder.max_content_tokens * settings.chunk_overlap_ratio),
    )
    body = gemini_response("Good job everything works smoothly.")
    llm = make_llm_client(make_handler(body))
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    retriever = RetrievalService(
        chunk_store, pg_vector_store, doc_store, embedder, chunker, session_factory
    )
    answerer = AnswerService(llm, retriever)
    doc = DocumentDTO(
        uuid4(),
        "doc.txt",
        str(f),
        "0123456789abcdef",
        {"creator": "assasino", "size": 100},
    )

    ch_ids = [uuid4() for i in range(6)]
    chunks = [
        ChunkDTO(ch_ids[0], "Life is beautiful.", doc.id, 0),
        ChunkDTO(ch_ids[1], "Sun is shining", doc.id, 1),
        ChunkDTO(ch_ids[2], "Night and day are late.", doc.id, 2),
        ChunkDTO(ch_ids[3], "He is mean.", doc.id, 3),
        ChunkDTO(
            ch_ids[4],
            "Meaning of life is someting noone can answer excpet C++",
            doc.id,
            4,
        ),
        ChunkDTO(ch_ids[5], "Car ate my dog.", doc.id, 5),
    ]
    vectors = embedder.embed_document([ch.content for ch in chunks])

    await doc_store.add_document(session, doc)
    await chunk_store.add_chunks(session, chunks)
    await pg_vector_store.add_vectors(
        session, [(ch_ids[i], vec) for i, vec in enumerate(vectors)]
    )
    # commit so the retriever's own session sees the doc, chunks and vectors.
    await session.commit()

    # threshold=2.0 (cosine-distance max) keeps the old no-threshold top-k behaviour these
    # ordering assertions were written against.
    found_k = await retriever.search_topk_chunks("What is the meaning of life?", 3, 2.0)
    assert found_k[0] == "Meaning of life is someting noone can answer excpet C++"
    assert found_k[1] == "Life is beautiful."
    assert found_k[2] == "Sun is shining"

    resp = await answerer.get_answer("What is the meaning of life?")
    assert resp == "Good job everything works smoothly."
