from rag_app.stores.document_store import DocStore
from rag_app.stores.vector_store import VectorStore
from rag_app.stores.chunk_store import ChunkStore

from rag_app.schemas import DocumentDTO
from rag_app.schemas import ChunkDTO
from rag_app.schemas import Embedding

from rag_app.chunkings.chunker import Chunker
from rag_app.embeddings.embedder import Embedder

from os.path import isfile
import aiofiles
from uuid import UUID, uuid4 

class IngestionService:
    # all DI (dependency injection), just references to once created in API layer
    def __init__(self, doc_store: DocStore, chunk_store: ChunkStore, vector_store: VectorStore, embedder: Embedder, chunker: Chunker) -> None:
        self.doc_store = doc_store
        self.chunk_store = chunk_store
        self.vec_store = vector_store
        self.embedder = embedder
        self.chunker = chunker
    async def store_document(self, document: DocumentDTO) -> None:
        # guards
        if not isfile(document.path_raw_content):
            raise ValueError(f"{document.path_raw_content} isn't a valid path to document")
        if await self.doc_store.exists(document.id):
            return
        async with aiofiles.open(document.path_raw_content, mode='r') as f:
            doc_content = await f.read()
        if not doc_content:
            raise ValueError("Can't store empty document") 
        
        # store document
        await self.doc_store.add_document(document)
        # create chunks
        chunks: list[str] = self.chunker.chunk_text(doc_content)
        # store chunks - list of ChunkDTOs
        chunk_dtos: list[ChunkDTO] = [ChunkDTO(uuid4(), ch, document.id, position) for position, ch in enumerate(chunks)]
        await self.chunk_store.add_chunks(chunk_dtos)
        # create vectors - here just list of str 
        vectors = self.embedder.embed_document(chunks) 
        # store vectors - expects tuple(id, Embedding)
        await self.vec_store.add_vectors([(ch.id, vector) for ch, vector in zip(chunk_dtos, vectors, strict=True)])
    
    