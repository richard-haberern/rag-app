from collections.abc import Sequence
from uuid import UUID
from numpy import ndarray
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rag_app.config import get_settings
from rag_app.models.vector import Vector
from rag_app.schemas import Embedding


class VectorStore:
    def __init__(self) -> None:
        self._dim = get_settings().embed_dim

    def _check_dim(self, vector: Embedding) -> None:
        if len(vector) != self._dim:
            raise ValueError(f"Vector has {len(vector)} dims, expected {self._dim}")

    async def add_vector(self, session: AsyncSession, chunk_id: UUID, vector: Embedding) -> None:
        self._check_dim(vector)
        session.add(Vector(chunk_id=chunk_id, content=vector))

    async def add_vectors(self, session: AsyncSession, items: Sequence[tuple[UUID, Embedding]]) -> None:
        for _, vector in items:
            self._check_dim(vector)
        session.add_all(
            [Vector(chunk_id=chunk_id, content=vector) for chunk_id, vector in items]
        )

    async def get_vector_values_by_chunk_id(self, session: AsyncSession, chunk_id: UUID) -> Embedding:
        vector = await session.get(Vector, chunk_id)
        if vector is None:
            raise ValueError(f"Vector for chunk {chunk_id} doesn't exist")
        # always numpy float32 - just runtime check
        return cast(ndarray, vector.content).tolist()

    async def search(self, session: AsyncSession, query_vector: Embedding, k: int) -> list[tuple[UUID, float]]:
        if k <= 0:
            raise ValueError("k has to be >= 1")
        self._check_dim(query_vector)
        distance = Vector.content.cosine_distance(query_vector)
        stmt = select(Vector.chunk_id, distance).order_by(distance).limit(k)
        result = await session.execute(stmt)
        return [(chunk_id, dist) for chunk_id, dist in result]
