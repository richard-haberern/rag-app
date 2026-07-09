from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rag_app.models.chunk import Chunk
from rag_app.schemas import ChunkDTO

from rag_app.exceptions import ChunkNotFound


def _to_dto(chunk: Chunk) -> ChunkDTO:
    return ChunkDTO(
        id=chunk.id,
        content=chunk.content,
        document_id=chunk.document_id,
        position=chunk.position,
    )


class ChunkStore:
    async def add_chunks(
        self, session: AsyncSession, chunks: Sequence[ChunkDTO]
    ) -> None:
        session.add_all(
            [
                Chunk(
                    id=c.id,
                    content=c.content,
                    document_id=c.document_id,
                    position=c.position,
                )
                for c in chunks
            ]
        )

    async def get_chunk(self, session: AsyncSession, id: UUID) -> ChunkDTO:
        chunk = await session.get(Chunk, id)
        if chunk is None:
            raise ChunkNotFound(f"Chunk {id} doesn't exist")
        return _to_dto(chunk)

    async def get_chunks_by_ids(
        self, session: AsyncSession, ids: Sequence[UUID]
    ) -> list[ChunkDTO]:
        # Text-fetch half of two-step retrieval. Order is not guaranteed here; the caller
        # holds the (chunk_id, distance) ranking from VectorStore.search.
        result = await session.execute(
            select(Chunk).where(Chunk.id.in_(ids)).order_by(Chunk.position)
        )
        return [_to_dto(c) for c in result.scalars()]

    async def get_chunks_by_document(
        self, session: AsyncSession, document_id: UUID
    ) -> list[ChunkDTO]:
        result = await session.execute(
            select(Chunk)
            .where(Chunk.document_id == document_id)
            .order_by(Chunk.position)
        )
        chunks = list(result.scalars())
        if not chunks:
            raise ChunkNotFound(f"No chunks to document with {document_id}")
        return [_to_dto(c) for c in chunks]

    async def get_chunk_ids_by_document(
        self, session: AsyncSession, document_id: UUID
    ) -> list[UUID]:
        # Deletion-side counterpart to get_chunks_by_document: an empty result is a valid
        # state (nothing to purge), so this returns [] instead of raising.
        result = await session.execute(
            select(Chunk.id).where(Chunk.document_id == document_id)
        )
        return list(result.scalars())
