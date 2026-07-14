from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from httpx import AsyncClient

from rag_app.api.routes import ingest, query, dev
from rag_app.chunkings.factory import build_chunker
from rag_app.db.engine import make_engine, make_sessionmaker
from rag_app.embeddings.embedder import Embedder
from rag_app.llm.factory import build_llm_client
from rag_app.services.answerer import AnswerService
from rag_app.services.ingestor import IngestionService
from rag_app.services.retriever import RetrievalService
from rag_app.stores.chunk_store import ChunkStore
from rag_app.stores.document_store import DocStore
from rag_app.config import get_settings
from rag_app.stores.pg_vector_store import PgVectorStore
from rag_app.exceptions import AppError
from rag_app.stores.users_store import UserStore

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Runtime connects as the least-privilege app_user (APP_DATABASE_URL) so RLS applies;
    # Schema (extension + tables + RLS + grants)
    # is owned by Alembic and must be applied (alembic upgrade head, as the owner) before boot
    # -- app_user has DML grants only, so there is no init_db here.
    app.state.engine = make_engine(get_settings().app_sqlalchemy_url)
    app.state.session_maker = make_sessionmaker(app.state.engine)
    app.state.http = AsyncClient()
    app.state.embedder = Embedder()
    app.state.chunker = build_chunker(app.state.embedder)
    app.state.llm_client = build_llm_client(app.state.http)
    app.state.chunk_store = ChunkStore()
    app.state.doc_store = DocStore()
    app.state.vec_store = PgVectorStore()
    app.state.user_store = UserStore()
    app.state.ingestor = IngestionService(
        app.state.doc_store,
        app.state.chunk_store,
        app.state.vec_store,
        app.state.embedder,
        app.state.chunker,
    )
    app.state.retriever = RetrievalService(
        app.state.chunk_store,
        app.state.vec_store,
        app.state.doc_store,
        app.state.embedder,
        app.state.chunker,
    )
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
app.include_router(dev.router)

# Static frontend (homepage + demo). Mounted at "/" but registered AFTER the routers
# and FastAPI's built-in /docs//redoc//openapi.json, and Starlette matches routes in
# registration order — so the mount only catches paths nothing else claimed.
# html=True makes "/" serve index.html. The directory comes from settings.static_dir
# (env var STATIC_DIR): defaults to the repo-root static/ locally, and /app/static in
# Docker (set by the Dockerfile). StaticFiles raises at startup if the dir is missing.
app.mount(
    "/",
    StaticFiles(directory=get_settings().static_dir, html=True),
    name="static",
)


# Every deliberate app error carries its own status_code, so one handler covers the whole
# AppError tree (Starlette dispatches to the most specific registered class by MRO).
@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})


# Last-resort envelope for anything unforeseen: consistent JSON shape, no internal leak.
@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content={"detail": "Internal server error."})
