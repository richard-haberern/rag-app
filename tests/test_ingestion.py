"""IngestionService.store_document — the chunk -> embed -> store path (MVP steps 1-4).

Uses the FakeEmbedder/FakeTokenizer doubles so nothing loads SentenceTransformer or hits the
network; the stores, sessions and Chunker are real, against the test DB."""

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker
from uuid import uuid4

from rag_app.chunkings.chunker import Chunker
from rag_app.schemas import DocumentDTO
from rag_app.services.ingestor import IngestionService


# 40 whitespace-tokens; with max_size=20 / overlap=5 the FakeTokenizer windowing yields 3 chunks
# (same arithmetic as test_chunking.test_chunker_1), so the stored chunk/vector count is known.
_FORTY_WORDS = """w01 w02 w03 w04 w05 w06 w07 w08 w09 w10 w11 w12 w13 w14 w15 w16 w17 w18 w19 w20 w21 w22 w23 w24 w25 w26 w27 w28 w29 w30 w31 w32 w33 w34 w35 w36 w37 w38 w39 w40"""
_EXPECTED_CHUNKS = 3


def _make_ingestor(
    engine, doc_store, chunk_store, pg_vector_store, fake_embedder, fake_tokenizer
):
    chunker = Chunker(fake_tokenizer, 20, 5)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return IngestionService(
        doc_store, chunk_store, pg_vector_store, fake_embedder, chunker, session_factory
    )


async def test_store_document_persists_doc_chunks_vectors(
    engine,
    doc_store,
    chunk_store,
    pg_vector_store,
    fake_embedder,
    fake_tokenizer,
    new_session,
    db_tests,
):
    doc = DocumentDTO(uuid4(), "doc.txt", "hash-it", _FORTY_WORDS, {"creator": "ambulance"})
    ingestor = _make_ingestor(
        engine, doc_store, chunk_store, pg_vector_store, fake_embedder, fake_tokenizer
    )

    await ingestor.store_document(doc)

    async with new_session() as s:
        ret_doc = await doc_store.get_document(s, doc.id)
        chunks = await chunk_store.get_chunks_by_document(s, doc.id)
        vectors = [
            await pg_vector_store.get_vector_values_by_chunk_id(ch.id) for ch in chunks
        ]

    assert ret_doc.id == doc.id
    assert ret_doc.content_hash == doc.content_hash
    assert len(chunks) == _EXPECTED_CHUNKS
    assert [ch.position for ch in chunks] == list(range(_EXPECTED_CHUNKS))
    # One vector per chunk, each the configured pgvector dimension.
    assert len(vectors) == _EXPECTED_CHUNKS
    assert all(len(v) == fake_embedder.dimension for v in vectors)


async def test_store_document_dedupes_on_content_hash(
    engine,
    doc_store,
    chunk_store,
    pg_vector_store,
    fake_embedder,
    fake_tokenizer,
    new_session,
    db_tests,
):
    # Two distinct documents (different ids) sharing a content_hash: the second is a no-op because
    # DocStore.exists matches on content_hash.
    doc1 = DocumentDTO(uuid4(), "first.txt", "same-hash", _FORTY_WORDS, {})
    doc2 = DocumentDTO(uuid4(), "second.txt", "same-hash", _FORTY_WORDS, {})
    ingestor = _make_ingestor(
        engine, doc_store, chunk_store, pg_vector_store, fake_embedder, fake_tokenizer
    )

    await ingestor.store_document(doc1)
    await ingestor.store_document(doc2)

    async with new_session() as s:
        assert (await doc_store.get_document(s, doc1.id)).id == doc1.id
        with pytest.raises(ValueError):
            await doc_store.get_document(s, doc2.id)
        # Only doc1's chunks exist; doc2 never got past the dedupe short-circuit.
        assert (
            len(await chunk_store.get_chunks_by_document(s, doc1.id))
            == _EXPECTED_CHUNKS
        )


async def test_store_document_rejects_whitespace_only(
    engine,
    doc_store,
    chunk_store,
    pg_vector_store,
    fake_embedder,
    fake_tokenizer,
    db_tests,
):
    doc = DocumentDTO(uuid4(), "blank.txt", "hash-blank", "   \n\t \v \n", {})
    ingestor = _make_ingestor(
        engine, doc_store, chunk_store, pg_vector_store, fake_embedder, fake_tokenizer
    )

    with pytest.raises(ValueError):
        await ingestor.store_document(doc)

