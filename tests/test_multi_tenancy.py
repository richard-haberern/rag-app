from rag_app.services.ingestor import IngestionService
from rag_app.services.retriever import RetrievalService
from rag_app.chunkings.chunker import Chunker
from rag_app.schemas import DocumentDTO
from uuid import uuid4
import pytest
from rag_app.exceptions import DocumentExists


def _make_ingestor(doc_store, chunk_store, vec_store, fake_embedder, fake_tokenizer):
    chunker = Chunker(fake_tokenizer, 20, 5)
    return IngestionService(doc_store, chunk_store, vec_store, fake_embedder, chunker)


def _make_retriever(doc_store, chunk_store, vec_store, fake_embedder, fake_tokenizer):
    chunker = Chunker(fake_tokenizer, 20, 5)
    return RetrievalService(chunk_store, vec_store, doc_store, fake_embedder, chunker)


async def test_A_stores_B_reads_nothing(
    app_session,
    anonymous,
    doc_store,
    chunk_store,
    vec_store,
    fake_embedder,
    fake_tokenizer,
    db_tests,
):
    ingestor = _make_ingestor(
        doc_store, chunk_store, vec_store, fake_embedder, fake_tokenizer
    )
    retriever = _make_retriever(
        doc_store, chunk_store, vec_store, fake_embedder, fake_tokenizer
    )

    doc_tenant_A = DocumentDTO(
        uuid4(),
        "file1.txt",
        "0123456789abcdef",
        "some amazing content in the file",
        (await anonymous()).owner_id,
        {"creator": "assasino", "size": 100},
    )
    async with app_session(doc_tenant_A.owner_id) as s:
        await ingestor.store_document(s, doc_tenant_A)
    tenant_B = (await anonymous()).owner_id
    async with app_session(tenant_B) as s:
        assert await retriever.get_stored_documents_ids(s) == []


async def test_A_B_stores_A_reads(
    app_session,
    anonymous,
    doc_store,
    chunk_store,
    vec_store,
    fake_embedder,
    fake_tokenizer,
    db_tests,
):
    ingestor = _make_ingestor(
        doc_store, chunk_store, vec_store, fake_embedder, fake_tokenizer
    )
    retriever = _make_retriever(
        doc_store, chunk_store, vec_store, fake_embedder, fake_tokenizer
    )

    doc_tenant_A = DocumentDTO(
        uuid4(),
        "file1.txt",
        "0123456789abcde",
        "some amazing content in the file",
        (await anonymous()).owner_id,
        {"creator": "assasino", "size": 100},
    )
    doc_tenant_B = DocumentDTO(
        uuid4(),
        "file1.txt",
        "0123456789abcdefgh",
        "some amazing content in the file that should be different",
        (await anonymous()).owner_id,
        {"creator": "legendario", "size": 123},
    )
    async with app_session(doc_tenant_A.owner_id) as s:
        await ingestor.store_document(s, doc_tenant_A)
    async with app_session(doc_tenant_B.owner_id) as s:
        await ingestor.store_document(s, doc_tenant_B)
    async with app_session(doc_tenant_A.owner_id) as s:
        ret_doc = await retriever.get_document(s, doc_tenant_A.id)
        assert ret_doc.id == doc_tenant_A.id
        assert ret_doc.filename == doc_tenant_A.filename
        assert ret_doc.content_hash == doc_tenant_A.content_hash
        assert ret_doc.content == doc_tenant_A.content
        assert ret_doc.owner_id == doc_tenant_A.owner_id
        assert ret_doc.doc_metadata == doc_tenant_A.doc_metadata
        assert await retriever.get_stored_documents_ids(s) == [doc_tenant_A.id]
    async with app_session(doc_tenant_B.owner_id) as s:
        ret_doc = await retriever.get_document(s, doc_tenant_B.id)
        assert ret_doc.id == doc_tenant_B.id
        assert ret_doc.filename == doc_tenant_B.filename
        assert ret_doc.content_hash == doc_tenant_B.content_hash
        assert ret_doc.content == doc_tenant_B.content
        assert ret_doc.owner_id == doc_tenant_B.owner_id
        assert ret_doc.doc_metadata == doc_tenant_B.doc_metadata
        assert await retriever.get_stored_documents_ids(s) == [doc_tenant_B.id]


async def test_A_stores_no_owner_reads(
    app_session,
    anonymous,
    doc_store,
    chunk_store,
    vec_store,
    fake_embedder,
    fake_tokenizer,
    db_tests,
):
    ingestor = _make_ingestor(
        doc_store, chunk_store, vec_store, fake_embedder, fake_tokenizer
    )
    retriever = _make_retriever(
        doc_store, chunk_store, vec_store, fake_embedder, fake_tokenizer
    )

    doc_tenant_A = DocumentDTO(
        uuid4(),
        "file1.txt",
        "0123456789abcdef",
        "some amazing content in the file",
        (await anonymous()).owner_id,
        {"creator": "assasino", "size": 100},
    )
    async with app_session(doc_tenant_A.owner_id) as s:
        await ingestor.store_document(s, doc_tenant_A)

    async with app_session() as s:
        assert await retriever.get_stored_documents_ids(s) == []


async def test_dedup_on_content_and_owner(
    app_session,
    anonymous,
    doc_store,
    chunk_store,
    vec_store,
    fake_embedder,
    fake_tokenizer,
    db_tests,
):
    ingestor = _make_ingestor(
        doc_store, chunk_store, vec_store, fake_embedder, fake_tokenizer
    )

    doc_tenant_A = DocumentDTO(
        uuid4(),
        "file1.txt",
        "0123456789abcdef",
        "some amazing content in the file",
        (await anonymous()).owner_id,
        {"creator": "assasino", "size": 100},
    )
    doc_tenant_B = DocumentDTO(
        uuid4(),
        "file1.txt",
        "0123456789abcdef",
        "some amazing content in the file",
        (await anonymous()).owner_id,
        {"creator": "assasino", "size": 100},
    )
    doc_tenant_A_dup = DocumentDTO(
        uuid4(),
        "file1.txt",
        "0123456789abcdef",
        "some amazing content in the file",
        doc_tenant_A.owner_id,
        {"creator": "assasino", "size": 100},
    )
    async with app_session(doc_tenant_A.owner_id) as s:
        await ingestor.store_document(s, doc_tenant_A)

    async with app_session(doc_tenant_B.owner_id) as s:
        await ingestor.store_document(s, doc_tenant_B)

    with pytest.raises(DocumentExists):
        async with app_session(doc_tenant_A_dup.owner_id) as s:
            await ingestor.store_document(s, doc_tenant_A_dup)
