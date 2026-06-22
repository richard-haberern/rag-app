from contextlib import asynccontextmanager

from fastapi import FastAPI

from httpx import AsyncClient

from rag_app.app.routes import ingest
from rag_app.app.routes import query

from rag_app.db.engine import make_engine
from rag_app.db.engine import make_sessionmaker
from rag_app.llm.factory import build_llm_client
from rag_app.stores.chunk_store import ChunkStore
from rag_app.stores.vector_store import VectorStore
from rag_app.stores.document_store import DocStore
from rag_app.services.answerer import AnswerService
from rag_app.services.retriever import RetrievalService
from rag_app.services.ingestor import IngestionService
from rag_app.chunkings.factory import build_chunker
from rag_app.embeddings.embedder import Embedder



@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.engine = make_engine()
    app.state.session_maker = make_sessionmaker(app.state.engine)
    app.state.http = AsyncClient()
    app.state.embedder = Embedder()
    app.state.chunker = build_chunker(app.state.embedder)
    app.state.llm_client = build_llm_client(app.state.http)
    app.state.chunk_store = ChunkStore(app.state.session_maker)
    app.state.doc_store = DocStore(app.state.session_maker)
    app.state.vec_store = VectorStore(app.state.session_maker)
    app.state.ingestor = IngestionService(app.state.doc_store, app.state.chunk_store, app.state.vec_store, app.state.embedder, app.state.chunker)
    app.state.retriever = RetrievalService(app.state.chunk_store, app.state.vec_store, app.state.doc_store, app.state.embedder, app.state.chunker)
    app.state.answerer = AnswerService(app.state.llm_client, app.state.retriever)
    
    yield

    await app.state.engine.dispose()
    await app.state.http.aclose()


app = FastAPI(
    title="Richies RAG-app",
    description="This is v1 of my first real project RAG-app",
    lifespan=lifespan, 
)
app.include_router(ingest.router)
app.include_router(query.router)
