from fastapi import Request, Response
from itsdangerous import Signer
from random import random
from uuid import uuid4, UUID

from sqlalchemy import select, delete, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from rag_app.config import get_settings
from rag_app.models import User


def _signer() -> Signer:
    key = get_settings().secret_key
    if key is None:
        raise ValueError("Secret Key is missing.")
    return Signer(key)


async def _check_owner(session: AsyncSession, owner_id: UUID) -> bool:
    """True if owner_id names a user that still exists and is within its TTL. The TTL check
    uses the DB clock (func.now()) to avoid app/DB timezone skew; TTL is a timedelta and
    renders as an interval."""
    ttl = get_settings().TTL
    res = await session.execute(
        select(User.id).where(
            and_(User.id == owner_id, func.now() < User.created_at + ttl)
        )
    )
    return res.scalar_one_or_none() is not None


async def _sweep_db(request: Request) -> None:
    """Delete users past their TTL. ON DELETE CASCADE from documents.owner_id purges their
    documents (and, in turn, chunks/vectors) -- an FK cascade, so it runs regardless of RLS
    even though this session has no app.owner_id set."""
    ttl = get_settings().TTL
    async with request.app.state.session_maker.begin() as s:
        await s.execute(delete(User).where(User.created_at + ttl < func.now()))


async def _mint(request: Request, response: Response) -> UUID:
    """Create a fresh anonymous identity: (probabilistically) sweep, insert the users row in
    its own committed transaction (so the later document insert's owner_id FK is satisfiable),
    and set the signed cookie."""
    if random() < 0.1:
        await _sweep_db(request)

    new_id = uuid4()
    async with request.app.state.session_maker.begin() as s:
        await request.app.state.user_store.add_user(s, new_id)

    response.set_cookie(
        "owner",
        _signer().sign(str(new_id)).decode(),
        max_age=get_settings().cookie_expire,
        httponly=True,
        samesite="lax",
        secure=get_settings().secure,
    )
    return new_id
