import re
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from rag_app.chunkings.chunker import Chunker
from rag_app.embeddings.embedder import Embedder
from rag_app.schemas import ChunkDTO, DocumentDTO
from rag_app.stores.chunk_store import ChunkStore
from rag_app.stores.document_store import DocStore
from rag_app.stores.vector_store import VectorStore


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
                return
        if not document.content or not re.search(r"\w", document.content):
            raise ValueError("Can't store document without characters in it")

        # create chunks
        chunks: list[str] = self.chunker.chunk_text(document.content)
        chunk_dtos: list[ChunkDTO] = [
            ChunkDTO(uuid4(), ch, document.id, position)
            for position, ch in enumerate(chunks)
        ]
        # create vectors - here just list of str
        vectors = self.embedder.embed_document(chunks)
        # auto-commits / rollback - atomic transaction
        async with self._session_factory.begin() as session:
            await self.doc_store.add_document(session, document)
            await self.chunk_store.add_chunks(session, chunk_dtos)
        async with self._session_factory.begin() as session:
            await self.vec_store.add_vectors(
                session,
                [
                    (ch.id, vector)
                    for ch, vector in zip(chunk_dtos, vectors, strict=True)
                ],
            )
