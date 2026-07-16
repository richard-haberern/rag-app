from rag_app.services.answerer import AnswerService
from rag_app.services.ingestor import IngestionService
from rag_app.services.retriever import RetrievalService

from sqlalchemy import text
from itsdangerous import BadSignature

from fastapi import Request, Response, Depends

from typing import Annotated, Any
from uuid import UUID

from rag_app.api._helpers import _mint, _check_owner, _signer


def get_answerer(request: Request) -> AnswerService:
    return request.app.state.answerer


def get_ingestor(request: Request) -> IngestionService:
    return request.app.state.ingestor


def get_retriever(request: Request) -> RetrievalService:
    return request.app.state.retriever


async def resolve_owner(request: Request) -> UUID | None:
    """Validate the signed `owner` cookie against the users registry. No mint, no cookie
    write. Returns the owner UUID if the cookie is present, well-signed, and names a user
    still within its TTL; otherwise None (reads then run with the GUC unset -> RLS empties them)."""
    raw = request.cookies.get("owner")
    if raw is None:
        return None
    try:
        owner_id = UUID(_signer().unsign(raw).decode())
    except (BadSignature, ValueError):
        return None
    async with request.app.state.session_maker.begin() as s:
        return owner_id if await _check_owner(s, owner_id) else None


async def require_owner(
    request: Request,
    response: Response,
    owner: Annotated[UUID | None, Depends(resolve_owner)],
) -> UUID:
    """Owner for write paths: reuse a valid identity, else mint one (users row + signed
    cookie, with a probabilistic sweep of expired users)."""
    if owner is not None:
        return owner
    return await _mint(request, response)


async def set_guc_rw(
    request: Request, owner_id: Annotated[UUID, Depends(require_owner)]
) -> Any:
    """Request-scoped session for writes: app.owner_id is always set (require_owner
    guarantees an identity). set_config(..., true) is transaction-local, so it lives exactly
    as long as this transaction and every query on `s` is RLS-scoped to the owner."""
    async with request.app.state.session_maker.begin() as s:
        await s.execute(
            text("SELECT set_config('app.owner_id', :id, true)"), {"id": str(owner_id)}
        )
        yield s


async def set_guc_ro(
    request: Request, owner_id: Annotated[UUID | None, Depends(resolve_owner)]
) -> Any:
    """Request-scoped session for reads. With no valid owner the GUC is left unset ->
    current_setting('app.owner_id', true) is NULL -> RLS returns nothing, and no user is
    minted (reads never create identities)."""
    async with request.app.state.session_maker.begin() as s:
        if owner_id is not None:
            await s.execute(
                text("SELECT set_config('app.owner_id', :id, true)"),
                {"id": str(owner_id)},
            )
        yield s
