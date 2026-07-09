from collections.abc import Sequence
from uuid import UUID

from numpy import asarray
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from rag_app.models.vector import Vector
from rag_app.schemas import Embedding
from rag_app.stores.vector_store import _check_dim
from rag_app.exceptions import VectorNotFound


class PgVectorStore:
    def __init__(self, session_maker: async_sessionmaker[AsyncSession]) -> None:
        self.session_maker = session_maker

    async def add_vector(self, chunk_id: UUID, vector: Embedding) -> None:
        _check_dim(vector)
        async with self.session_maker.begin() as session:
            session.add(Vector(chunk_id=chunk_id, content=vector))

    async def add_vectors(self, items: Sequence[tuple[UUID, Embedding]]) -> None:
        for _, vector in items:
            _check_dim(vector)
        async with self.session_maker.begin() as session:
            session.add_all(
                [
                    Vector(chunk_id=chunk_id, content=vector)
                    for chunk_id, vector in items
                ]
            )

    async def get_vector_values_by_chunk_id(self, chunk_id: UUID) -> Embedding:
        async with self.session_maker.begin() as session:
            vector = await session.get(Vector, chunk_id)
        if vector is None:
            raise VectorNotFound(f"Vector for chunk {chunk_id} doesn't exist")
        # if it is not an ndarray cast it if yes do nothing
        return asarray(vector.content).tolist()

    async def remove_vector(self, chunk_id: UUID) -> None:
        async with self.session_maker.begin() as session:
            stmt = delete(Vector).where(Vector.chunk_id == chunk_id)
            await session.execute(stmt)

    async def remove_vectors(self, chunk_ids: Sequence[UUID]) -> None:
        async with self.session_maker.begin() as session:
            stmt = delete(Vector).where(Vector.chunk_id.in_(chunk_ids))
            await session.execute(stmt)

    async def search(
        self, query_vector: Embedding, k: int, threshold: float
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
        async with self.session_maker() as session:
            result = await session.execute(stmt)
        return [(chunk_id, dist) for chunk_id, dist in result]
