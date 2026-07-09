import re
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from rag_app.chunkings.chunker import Chunker
from rag_app.embeddings.embedder import Embedder
from rag_app.schemas import ChunkDTO, DocumentDTO
from rag_app.stores.chunk_store import ChunkStore
from rag_app.stores.document_store import DocStore
from rag_app.stores.vector_store import VectorStore
from rag_app.exceptions import DocumentExists, EmptyDocument


class IngestionService:
    # all DI (dependency injection), just references to once created in API layer
    def __init__(
        self,
        doc_store: DocStore,
        chunk_store: ChunkStore,
        vector_store: VectorStore,
        embedder: Embedder,
        chunker: Chunker,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self.doc_store = doc_store
        self.chunk_store = chunk_store
        self.vec_store = vector_store
        self.embedder = embedder
        self.chunker = chunker
        self._session_factory = session_factory

    async def store_document(self, document: DocumentDTO) -> None:
        async with self._session_factory.begin() as session:
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
        # create vectors - here just list of str
        vectors = self.embedder.embed_document(chunks)
        # auto-commits / rollback - atomic transaction. The exists() pre-check above handles the
        # common case; this guards the TOCTOU race where two identical uploads both pass it.
        # content_hash is the only unique constraint a fresh-uuid insert can violate here.
        try:
            async with self._session_factory.begin() as session:
                await self.doc_store.add_document(session, document)
                await self.chunk_store.add_chunks(session, chunk_dtos)
        except IntegrityError as exc:
            raise DocumentExists() from exc

        await self.vec_store.add_vectors(
            [(ch.id, vector) for ch, vector in zip(chunk_dtos, vectors, strict=True)],
        )

    async def remove_document(self, doc_id: UUID) -> None:
        # Read chunk ids before deleting: the pg cascade removes chunks, but an external
        # vector store (Chroma) still needs them to purge its vectors.
        async with self._session_factory.begin() as session:
            ch_ids = await self.chunk_store.get_chunk_ids_by_document(session, doc_id)
        # Delete the vectors first so we don't run into a orphan vectors stage.
        # Deletes the vectors in both stores
        await self.vec_store.remove_vectors(ch_ids)
        # This will delete the docs and chunks with DELETE ON CASCADE
        # the vectors are already deleted
        # if we use PGvector 3 transactions but that is necessary for the swappable seam
        async with self._session_factory.begin() as session:
            await self.doc_store.remove_document(session, doc_id)
