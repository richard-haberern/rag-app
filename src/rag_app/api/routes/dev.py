from fastapi import APIRouter, HTTPException, Depends, Header
from typing import Annotated
from sqlalchemy.ext.asyncio import AsyncSession
from rag_app.api.deps import get_db_session
from rag_app.config import get_settings
from secrets import compare_digest
from sqlalchemy import text

router = APIRouter()


@router.get("/health")
def get_health_info() -> str:
    return "Everything is running"


@router.post("/admin/cleanup")
async def cleanup(
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    sweep_token: Annotated[str | None, Header(alias="sweep-token")] = None,
) -> None:
    secret_token = get_settings().sweep_token
    # Any auth failure — server misconfig, missing header, or mismatch — returns the same
    # 404 so the endpoint is indistinguishable from a non-route to an unauthenticated probe.
    if secret_token is None or sweep_token is None:
        raise HTTPException(status_code=404)
    if not compare_digest(secret_token, sweep_token):
        raise HTTPException(status_code=404)
    await db_session.execute(text("SELECT public.sweep_owners()"))
    await db_session.execute(text("SELECT public.sweep_sessions()"))
