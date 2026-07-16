"""IngestionService.store_document — the chunk -> embed -> store path (MVP steps 1-4).

Uses the FakeEmbedder/FakeTokenizer doubles so nothing loads SentenceTransformer or hits the
network; the stores, sessions and Chunker are real, against the test DB."""

import pytest
from uuid import uuid4

from rag_app.chunkings.chunker import Chunker
from rag_app.schemas import DocumentDTO
from rag_app.services.ingestor import IngestionService
from rag_app.services.retriever import RetrievalService
from rag_app.exceptions import (
    DocumentNotFound,
    VectorNotFound,
    EmptyDocument,
    DocumentExists,
)


# 40 whitespace-tokens; with max_size=20 / overlap=5 the FakeTokenizer windowing yields 3 chunks
# (same arithmetic as test_chunking.test_chunker_1), so the stored chunk/vector count is known.
_FORTY_WORDS = """w01 w02 w03 w04 w05 w06 w07 w08 w09 w10 w11 w12 w13 w14 w15 w16 w17 w18 w19 w20 w21 w22 w23 w24 w25 w26 w27 w28 w29 w30 w31 w32 w33 w34 w35 w36 w37 w38 w39 w40"""
_EXPECTED_CHUNKS = 3


def _make_ingestor(
    doc_store, chunk_store, vec_store, fake_embedder, fake_tokenizer
):
    chunker = Chunker(fake_tokenizer, 20, 5)
    return IngestionService(
        doc_store, chunk_store, vec_store, fake_embedder, chunker
    )


def _make_retriever(
    doc_store, chunk_store, vec_store, fake_embedder, fake_tokenizer
):
    chunker = Chunker(fake_tokenizer, 20, 5)
    return RetrievalService(
        chunk_store, vec_store, doc_store, fake_embedder, chunker
    )


async def test_store_document_persists_doc_chunks_vectors(
    doc_store,
    chunk_store,
    vec_store,
    fake_embedder,
    fake_tokenizer,
    new_session,
    tenant,
    db_tests,
):
    doc = DocumentDTO(
        uuid4(), "doc.txt", "hash-it", _FORTY_WORDS, await tenant(), {"creator": "ambulance"}
    )
    ingestor = _make_ingestor(
        doc_store, chunk_store, vec_store, fake_embedder, fake_tokenizer
    )
    async with new_session() as s:
        await ingestor.store_document(s, doc)
        await s.commit()

    async with new_session() as s:
        ret_doc = await doc_store.get_document(s, doc.id)
        chunks = await chunk_store.get_chunks_by_document(s, doc.id)
        vectors = [
            await vec_store.get_vector_values_by_chunk_id(s, ch.id) for ch in chunks
        ]

    assert ret_doc.id == doc.id
    assert ret_doc.content_hash == doc.content_hash
    assert len(chunks) == _EXPECTED_CHUNKS
    assert [ch.position for ch in chunks] == list(range(_EXPECTED_CHUNKS))
    # One vector per chunk, each the configured pgvector dimension.
    assert len(vectors) == _EXPECTED_CHUNKS
    assert all(len(v) == fake_embedder.dimension for v in vectors)


async def test_store_document_dedupes_on_content_hash(
    doc_store,
    chunk_store,
    vec_store,
    fake_embedder,
    fake_tokenizer,
    new_session,
    tenant,
    db_tests,
):
    # Two distinct documents (different ids) sharing a content_hash: the second is a no-op because
    # DocStore.exists matches on content_hash.
    doc1 = DocumentDTO(uuid4(), "first.txt", "same-hash", _FORTY_WORDS, await tenant(), {})
    doc2 = DocumentDTO(uuid4(), "second.txt", "same-hash", _FORTY_WORDS, await tenant(), {})
    ingestor = _make_ingestor(
        doc_store, chunk_store, vec_store, fake_embedder, fake_tokenizer
    )
    async with new_session() as s:
        await ingestor.store_document(s, doc1)
        await s.commit()
    async with new_session() as s:
        with pytest.raises(DocumentExists):
            await ingestor.store_document(s, doc2)

    async with new_session() as s:
        assert (await doc_store.get_document(s, doc1.id)).id == doc1.id
        with pytest.raises(DocumentNotFound):
            await doc_store.get_document(s, doc2.id)
        # Only doc1's chunks exist; doc2 never got past the dedupe short-circuit.
        assert (
            len(await chunk_store.get_chunks_by_document(s, doc1.id))
            == _EXPECTED_CHUNKS
        )


async def test_store_document_rejects_whitespace_only(
        doc_store,
    chunk_store,
    vec_store,
    fake_embedder,
    fake_tokenizer,
    new_session,
    tenant,
    db_tests,
):
    doc = DocumentDTO(uuid4(), "blank.txt", "hash-blank", "   \n\t \v \n", await tenant(), {})
    ingestor = _make_ingestor(
        doc_store, chunk_store, vec_store, fake_embedder, fake_tokenizer
    )
    async with new_session() as s:
        with pytest.raises(EmptyDocument):
            await ingestor.store_document(s, doc)


async def test_remove_document(
        doc_store,
    chunk_store,
    vec_store,
    fake_embedder,
    fake_tokenizer,
    db_tests,
    tenant,
    new_session,
):
    doc = DocumentDTO(uuid4(), "first.txt", "hash-of-the-file", _FORTY_WORDS, await tenant(), {})
    ingestor = _make_ingestor(
        doc_store, chunk_store, vec_store, fake_embedder, fake_tokenizer
    )
    retriever = _make_retriever(
        doc_store, chunk_store, vec_store, fake_embedder, fake_tokenizer
    )
    async with new_session() as s:
        await ingestor.store_document(s, doc)
        await s.commit()
    async with new_session() as s:
        ch_ids = await chunk_store.get_chunk_ids_by_document(s, doc.id)
    async with new_session() as s:
        await ingestor.remove_document(s, doc.id)
        await s.commit()
    async with new_session() as s:
        with pytest.raises(DocumentNotFound):
            await retriever.get_document(s, doc.id)
    async with new_session() as s:
        assert await chunk_store.get_chunks_by_ids(s, ch_ids) == []
        for ch_id in ch_ids:
            with pytest.raises(VectorNotFound):
                await vec_store.get_vector_values_by_chunk_id(s, ch_id)


async def test_get_stored_documents_ids(
        doc_store,
    chunk_store,
    vec_store,
    fake_embedder,
    fake_tokenizer,
    db_tests,
    tenant,
    new_session,
):
    ingestor = _make_ingestor(
        doc_store, chunk_store, vec_store, fake_embedder, fake_tokenizer
    )
    retriever = _make_retriever(
        doc_store, chunk_store, vec_store, fake_embedder, fake_tokenizer
    )
    docs_info = [
        (uuid4(), f"file-{i}.txt", f"hash-{i}", _FORTY_WORDS + str(i), await tenant(), {})
        for i in range(4)
    ]
    docs = [DocumentDTO(id, n, h, c, t, m) for id, n, h, c, t, m in docs_info]
    async with new_session() as s:
        for doc in docs:
            await ingestor.store_document(s, doc)
            await s.commit()

    async with new_session() as s:
        docs_ids = await retriever.get_stored_documents_ids(s)
    assert set(docs_ids) == {doc_info[0] for doc_info in docs_info}


async def test_get_stored_documents_full_info(
    doc_store,
    chunk_store,
    vec_store,
    fake_embedder,
    fake_tokenizer,
    db_tests,
    tenant,
    new_session,
):
    ingestor = _make_ingestor(
        doc_store, chunk_store, vec_store, fake_embedder, fake_tokenizer
    )
    retriever = _make_retriever(
        doc_store, chunk_store, vec_store, fake_embedder, fake_tokenizer
    )
    docs_info = [
        (uuid4(), f"file-{i}.txt", f"hash-{i}", _FORTY_WORDS + str(i), await tenant(), {})
        for i in range(4)
    ]
    docs = [DocumentDTO(id, n, h, c, t, m) for id, n, h, c, t, m in docs_info]
    async with new_session() as s:
        for doc in docs:
            await ingestor.store_document(s, doc)
        await s.commit()
    async with new_session() as s:
        docDTOs = await retriever.get_stored_documents_DTOs(s)
    by_id = {d.id: d for d in docDTOs}
    assert set(by_id) == {doc_info[0] for doc_info in docs_info}
    for id_, name, content_hash, content, owner_id, metadata in docs_info:
        d = by_id[id_]
        assert d.id == id_
        assert d.filename == name
        assert d.doc_metadata == metadata
