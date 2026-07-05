from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import AsyncClient

from rag_app.api.routes import ingest, query, dev
from rag_app.chunkings.factory import build_chunker
from rag_app.db.bootstrap import init_db
from rag_app.db.engine import make_engine, make_sessionmaker
from rag_app.embeddings.embedder import Embedder
from rag_app.llm.factory import build_llm_client
from rag_app.services.answerer import AnswerService
from rag_app.services.ingestor import IngestionService
from rag_app.services.retriever import RetrievalService
from rag_app.stores.chunk_store import ChunkStore
from rag_app.stores.document_store import DocStore
from rag_app.stores.chroma_vector_store import (
    ChromaVectorStore,
    connect,
    make_collection,
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await init_db()  # CREATE EXTENSION + create_all; idempotent, safe per boot
    app.state.engine = make_engine()
    app.state.session_maker = make_sessionmaker(app.state.engine)
    app.state.http = AsyncClient()
    app.state.embedder = Embedder()
    app.state.chunker = build_chunker(app.state.embedder)
    app.state.llm_client = build_llm_client(app.state.http)
    app.state.chunk_store = ChunkStore()
    app.state.doc_store = DocStore()
    app.state.client = await connect()  # blocks until the Chroma server is ready
    app.state.vec_store = ChromaVectorStore(await make_collection(app.state.client))
    app.state.ingestor = IngestionService(
        app.state.doc_store,
        app.state.chunk_store,
        app.state.vec_store,
        app.state.embedder,
        app.state.chunker,
        app.state.session_maker,
    )
    app.state.retriever = RetrievalService(
        app.state.chunk_store,
        app.state.vec_store,
        app.state.doc_store,
        app.state.embedder,
        app.state.chunker,
        app.state.session_maker,
    )
    app.state.answerer = AnswerService(app.state.llm_client, app.state.retriever)

    yield

    await app.state.engine.dispose()
    await app.state.http.aclose()
    # client has no close / aclose method - AsyncClient shouldn't leak


app = FastAPI(
    title="Richies RAG-app",
    description="This is v1 of my first real project RAG-app",
    lifespan=lifespan,
)
app.include_router(ingest.router)
app.include_router(query.router)
app.include_router(dev.router)


# Service/store layers signal failures with plain exceptions; translate them to HTTP here so
# they don't surface as opaque 500s. ValueError = bad input (over-long query, invalid/empty
# path). OSError = a referenced file is gone. NOTE: document-not-found is also a ValueError, so
# it currently maps to 400, not 404 — a precise 404 needs a dedicated NotFoundError (deferred).
@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(OSError)
async def os_error_handler(request: Request, exc: OSError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})
