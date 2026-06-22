from rag_app.stores.vector_store import VectorStore
from rag_app.stores.chunk_store import ChunkStore
from rag_app.stores.document_store import DocStore

from rag_app.chunkings.chunker import Chunker
from rag_app.embeddings.embedder import Embedder

from rag_app.schemas import DocumentDTO

from uuid import UUID

class RetrievalService:
    # all DI
    def __init__(self, chunk_store: ChunkStore, vector_store: VectorStore, doc_store: DocStore, embedder: Embedder, chunker: Chunker) -> None:
        self.chunk_store = chunk_store
        self.vec_store = vector_store
        self.doc_store = doc_store
        self.embedder = embedder
        self.chunker = chunker

    #later need to add threshold
    async def search_topk_chunks(self, query: str, k: int) -> list[str]:
        # add_special_tokens=False matches max_size (the content-token window the chunker uses).
        q_size = len(self.chunker.tokenizer(query, add_special_tokens=False)["input_ids"])
        if q_size > self.chunker.max_size:
            raise ValueError(f"Your query is too long {q_size}, max size for query is {self.chunker.max_size}")
        q_vector: list[float] = self.embedder.embed_query(query)[0]
        k_vectors = await self.vec_store.search(q_vector, k)
        k_chunks = await self.chunk_store.get_chunks_by_ids([ch_id for ch_id, _ in k_vectors])
        return [ch.content for ch in k_chunks]
    async def get_document_content(self, id: UUID) -> str:
        return await self.doc_store.get_document_content(id)
    async def get_document_DTO(self, id: UUID) -> DocumentDTO:
        return await self.doc_store.get_document(id)
     