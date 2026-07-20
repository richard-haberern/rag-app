import re
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from rag_app.chunkings.chunker import Chunker
from rag_app.embeddings.embedder import Embedder
from rag_app.schemas import ChunkDTO, DocumentDTO
from rag_app.stores.chunk_store import ChunkStore
from rag_app.stores.document_store import DocStore
from rag_app.stores.pg_vector_store import PgVectorStore
from rag_app.exceptions import DocumentExists, EmptyDocument


class IngestionService:
    # all DI (dependency injection), just references to once created in API layer
    def __init__(
        self,
        doc_store: DocStore,
        chunk_store: ChunkStore,
        vector_store: PgVectorStore,
        embedder: Embedder,
        chunker: Chunker,
    ) -> None:
        self.doc_store = doc_store
        self.chunk_store = chunk_store
        self.vec_store = vector_store
        self.embedder = embedder
        self.chunker = chunker

    async def store_document(
        self, session: AsyncSession, document: DocumentDTO
    ) -> None:
        if await self.doc_store.exists(session, document):
            raise DocumentExists()
        if not document.content or not re.search(r"\w", document.content):
            raise EmptyDocument("Can't store document without characters in it")

        # create chunks
        chunks: list[str] = self.chunker.chunk_text(document.content)
        chunk_dtos: list[ChunkDTO] = [
            ChunkDTO(uuid4(), ch, document.id, position)
            for position, ch in enumerate(chunks)
        ]
        # create vectors - here just list of str. Embedding is done outside the write
        # transaction below - it's slow CPU work and shouldn't hold a transaction open.
        vectors = self.embedder.embed_document(chunks)
        # Single atomic transaction: document, chunks and vectors all live in Postgres,
        # so they commit or roll back together - no orphan-vector window. The exists()
        # pre-check above handles the common case; the IntegrityError guard covers the
        # TOCTOU race where two identical uploads both pass it (content_hash + owner_id is the only
        # unique constraint a fresh-uuid insert can violate here). The unit-of-work orders
        # the inserts by FK dependency, so the chunks land before their vectors.
        try:
            await self.doc_store.add_document(session, document)
            await self.chunk_store.add_chunks(session, chunk_dtos)
            await self.vec_store.add_vectors(
                session,
                [
                    (ch.id, vector)
                    for ch, vector in zip(chunk_dtos, vectors, strict=True)
                ],
            )
        except IntegrityError as exc:
            raise DocumentExists() from exc

    async def remove_document(self, session: AsyncSession, doc_id: UUID) -> None:
        # Single atomic transaction. Deleting the document cascades to its chunks and, in
        # turn, their vectors via the FK ON DELETE CASCADE chain
        # (stored_vectors -> stored_chunks -> stored_documents), so one delete purges
        # everything with no orphans.
        await self.doc_store.remove_document(session, doc_id)
