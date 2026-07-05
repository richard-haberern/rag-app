import asyncio
from collections.abc import Sequence
from uuid import UUID
from numpy import ndarray
from typing import cast

from rag_app.schemas import Embedding
from rag_app.stores.vector_store import _check_dim
from rag_app.config import get_settings

from chromadb.api.models.AsyncCollection import AsyncCollection
from chromadb.api.async_api import AsyncClientAPI
from chromadb import AsyncHttpClient


async def make_client() -> AsyncClientAPI:
    host = get_settings().chroma_host
    port = get_settings().chroma_port
    return await AsyncHttpClient(
        host=host,
        port=port,
    )


async def make_collection(client: AsyncClientAPI) -> AsyncCollection:
    return await client.get_or_create_collection(
        name="VectorDB",
        embedding_function=None,
        configuration={"hnsw": {"space": "cosine"}},
    )


async def connect(
    retries: int | None = None,
    delay: float | None = None,
) -> AsyncClientAPI:
    """Wait for the Chroma server to accept connections, then return a client.

    The distroless chroma image has no curl/wget/python, so a compose
    healthcheck is impossible; readiness is enforced here. Note make_client()
    itself contacts the server (tenant validation), so the whole call is retried.
    """
    settings = get_settings()
    retries = settings.chroma_connect_retries if retries is None else retries
    delay = settings.chroma_connect_delay if delay is None else delay
    last_exc: Exception | None = None
    for _ in range(retries):
        try:
            client = await make_client()
            await client.heartbeat()
            return client
        except Exception as exc:
            last_exc = exc
            await asyncio.sleep(delay)
    raise RuntimeError(
        f"Chroma unreachable at {settings.chroma_host}:{settings.chroma_port} "
        f"after {retries} attempts: {last_exc}"
    )


class ChromaVectorStore:
    def __init__(self, collection: AsyncCollection) -> None:
        self.collection = collection

    async def add_vector(self, chunk_id: UUID, vector: Embedding) -> None:
        _check_dim(vector)
        await self.collection.add(
            ids=[str(chunk_id)],
            embeddings=[vector],  # type: ignore[arg-type]
        )

    async def add_vectors(self, items: Sequence[tuple[UUID, Embedding]]) -> None:
        for _, vector in items:
            _check_dim(vector)
        await self.collection.add(
            ids=[str(id) for id, _ in items],
            embeddings=[vector for _, vector in items],  # type: ignore[arg-type]
        )

    async def get_vector_values_by_chunk_id(self, chunk_id: UUID) -> Embedding:
        results = await self.collection.get(
            ids=[str(chunk_id)],
            include=["embeddings"],  # embeddings are NOT returned by default
        )
        embeddings = results["embeddings"]
        # missing id -> empty list (not None); None only if embeddings weren't included
        if embeddings is None or len(embeddings) == 0:
            raise ValueError(f"Vector for chunk {chunk_id} doesn't exist")
        # always numpy float32 - just runtime check
        return cast(ndarray, embeddings[0]).tolist()

    async def search(
        self, query_vector: Embedding, k: int, threshold: float
    ) -> list[tuple[UUID, float]]:
        _check_dim(query_vector)
        if k <= 0:
            raise ValueError("k has to be >= 1")
        result = await self.collection.query(
            query_embeddings=[query_vector],  # type: ignore[arg-type]
            n_results=k,
        )
        if result["distances"] is None or result["ids"] is None:
            return []
        return [
            (UUID(str(id)), dist)
            for id, dist in zip(result["ids"][0], result["distances"][0])
            if dist <= threshold
        ]
