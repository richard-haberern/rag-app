from collections.abc import Sequence
from uuid import UUID

from numpy import asarray
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from rag_app.config import get_settings
from rag_app.models.vector import Vector
from rag_app.schemas import Embedding
from rag_app.exceptions import VectorNotFound


def _check_dim(vector: Embedding) -> None:
    expected_dim = get_settings().embed_dim
    if len(vector) != expected_dim:
        raise ValueError(f"Vector has {len(vector)} dims, expected {expected_dim}")


class PgVectorStore:
    # Stateless like DocStore / ChunkStore: every method takes a caller-owned session
    # so vector writes join the same transaction as the doc/chunk writes (atomicity).
    async def add_vector(
        self, session: AsyncSession, chunk_id: UUID, vector: Embedding
    ) -> None:
        _check_dim(vector)
        session.add(Vector(chunk_id=chunk_id, content=vector))

    async def add_vectors(
        self, session: AsyncSession, items: Sequence[tuple[UUID, Embedding]]
    ) -> None:
        for _, vector in items:
            _check_dim(vector)
        session.add_all(
            [Vector(chunk_id=chunk_id, content=vector) for chunk_id, vector in items]
        )

    async def get_vector_values_by_chunk_id(
        self, session: AsyncSession, chunk_id: UUID
    ) -> Embedding:
        vector = await session.get(Vector, chunk_id)
        if vector is None:
            raise VectorNotFound(f"Vector for chunk {chunk_id} doesn't exist")
        # if it is not an ndarray cast it if yes do nothing
        return asarray(vector.content).tolist()

    async def remove_vector(self, session: AsyncSession, chunk_id: UUID) -> None:
        stmt = delete(Vector).where(Vector.chunk_id == chunk_id)
        await session.execute(stmt)

    async def remove_vectors(
        self, session: AsyncSession, chunk_ids: Sequence[UUID]
    ) -> None:
        stmt = delete(Vector).where(Vector.chunk_id.in_(chunk_ids))
        await session.execute(stmt)

    async def search(
        self,
        session: AsyncSession,
        query_vector: Embedding,
        k: int,
        threshold: float,
    ) -> list[tuple[UUID, float]]:
        if k <= 0:
            raise ValueError("k has to be >= 1")
        _check_dim(query_vector)
        # smaller cosine distance (1 - cosine_similarity) = closer = better
        distance = Vector.content.cosine_distance(query_vector)
        stmt = (
            select(Vector.chunk_id, distance)
            .where(distance <= threshold)
            .order_by(distance, Vector.chunk_id)
            .limit(k)
        )
        result = await session.execute(stmt)
        return [(chunk_id, dist) for chunk_id, dist in result]
