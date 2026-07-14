from uuid import UUID

from typing import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from rag_app.chunkings.chunker import Chunker
from rag_app.embeddings.embedder import Embedder
from rag_app.schemas import DocumentDTO
from rag_app.stores.chunk_store import ChunkStore
from rag_app.stores.document_store import DocStore
from rag_app.stores.pg_vector_store import PgVectorStore
from rag_app.exceptions import QueryTooLong


class RetrievalService:
    # all DI
    def __init__(
        self,
        chunk_store: ChunkStore,
        vector_store: PgVectorStore,
        doc_store: DocStore,
        embedder: Embedder,
        chunker: Chunker,
    ) -> None:
        self.chunk_store = chunk_store
        self.vec_store = vector_store
        self.doc_store = doc_store
        self.embedder = embedder
        self.chunker = chunker

    # later need to add threshold
    async def search_topk_chunks(
        self, session: AsyncSession, query: str, k: int, threshold: float
    ) -> list[str]:
        # add_special_tokens=False matches max_size (the content-token window the chunker uses).
        q_size = len(
            self.chunker.tokenizer(query, add_special_tokens=False)["input_ids"]
        )
        if q_size > self.chunker.max_size:
            raise QueryTooLong(
                f"Your query is too long {q_size}, max size for query is {self.chunker.max_size}"
            )
        q_vector: list[float] = self.embedder.embed_query(query)[0]
        
        k_vectors = await self.vec_store.search(session, q_vector, k, threshold)
        k_chunks = await self.chunk_store.get_chunks_by_ids(
            session, [ch_id for ch_id, _ in k_vectors]
        )
        # have to sort chunks by the vectors -> O(n)
        by_id = {ch.id: ch for ch in k_chunks}
        ordered_content = [
            by_id[ch_id].content for ch_id, _ in k_vectors if ch_id in by_id
        ]
        return ordered_content

    async def get_document_content(self, session: AsyncSession, id: UUID) -> str:
        return await self.doc_store.get_document_content(session, id)

    async def get_document(self, session: AsyncSession, id: UUID) -> DocumentDTO:
        return await self.doc_store.get_document(session, id)

    async def get_stored_documents_ids(self, session: AsyncSession,) -> Sequence[UUID]:
        return await self.doc_store.get_stored_documents_ids(session)

    async def get_stored_documents_DTOs(self, session: AsyncSession,) -> Sequence[DocumentDTO]:
        return await self.doc_store.get_stored_documents(session)
