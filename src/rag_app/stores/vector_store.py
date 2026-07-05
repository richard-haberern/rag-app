from collections.abc import Sequence
from typing import Protocol
from uuid import UUID


from rag_app.config import get_settings
from rag_app.schemas import Embedding


def _check_dim(vector: Embedding) -> None:
    expected_dim = get_settings().embed_dim
    if len(vector) != expected_dim:
        raise ValueError(f"Vector has {len(vector)} dims, expected {expected_dim}")


class VectorStore(Protocol):
    async def add_vector(self, chunk_id: UUID, vector: Embedding) -> None: ...
    async def add_vectors(self, items: Sequence[tuple[UUID, Embedding]]) -> None: ...
    async def get_vector_values_by_chunk_id(self, chunk_id: UUID) -> Embedding: ...
    async def search(
        self, query_vector: Embedding, k: int, threshold: float
    ) -> list[tuple[UUID, float]]: ...
