from rag_app.services.answerer import AnswerService
from rag_app.services.ingestor import IngestionService
from rag_app.services.retriever import RetrievalService
from rag_app.api._helpers import _hash_token
from rag_app.exceptions import InvalidSession

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi import Request, Depends

from typing import Annotated, Any
from uuid import UUID


def get_answerer(request: Request) -> AnswerService:
    return request.app.state.answerer


def get_ingestor(request: Request) -> IngestionService:
    return request.app.state.ingestor


def get_retriever(request: Request) -> RetrievalService:
    return request.app.state.retriever


async def get_db_session(request: Request) -> Any:
    async with request.app.state.session_maker.begin() as s:
        yield s


async def validate_session(
    request: Request, db_session: Annotated[AsyncSession, Depends(get_db_session)]
) -> Any | None:
    """Validates the session against the db and returns the owner_id if
    it is, otherwise None (reads then run with the GUC unset -> RLS empties them)."""
    token = request.cookies.get("session_token")
    if token is None:
        return None
    token_hash = _hash_token(token)
    res = await db_session.execute(
        text("SELECT public.validate_session(:token_hash)"), {"token_hash": token_hash}
    )
    return res.scalar_one()


async def set_guc(
    request: Request, owner_id: Annotated[UUID | None, Depends(validate_session)]
) -> Any:
    """Request-scoped session for writes and reads - now the app can't be used
    without a valid session (anonymous or logged in) set_config(..., true)
    is transaction-local, so it lives exactly as long as this transaction and
    every query on `s` is RLS-scoped to the owner."""
    async with request.app.state.session_maker.begin() as s:
        if owner_id is None:
            raise InvalidSession()
        await s.execute(
            text("SELECT set_config('app.owner_id', :id, true)"), {"id": str(owner_id)}
        )
        yield s
