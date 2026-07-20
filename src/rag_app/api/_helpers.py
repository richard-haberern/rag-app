from uuid import UUID
from secrets import token_urlsafe

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from hashlib import sha256
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError
from fastapi.concurrency import run_in_threadpool

_ph = PasswordHasher()

# Precomputed once at import so a login against a nonexistent username can still pay the
# same argon2 verification cost as a real one — closes the timing side-channel for user
# enumeration. The value is irrelevant; only that verifying against it takes as long.
_DUMMY_HASH = _ph.hash("dummy_password_for_constant_time_login")


def _hash_token(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


async def _hash_password(password: str) -> str:
    # running it off the event-loop to not stall out other events.
    # argon2 is on purpose CPU-heavy
    return await run_in_threadpool(_ph.hash, password)


async def _verify_password(password_hash: str, password: str) -> bool:
    # Same off-loop offload as _hash_password. Returns False on any argon2 verification
    # failure instead of raising, so callers branch on a plain bool.
    def _verify() -> bool:
        try:
            return _ph.verify(password_hash, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False

    return await run_in_threadpool(_verify)


async def _create_new_session(owner_id: UUID, db_session: AsyncSession) -> str:
    token = _get_new_token()
    await db_session.execute(
        text("SELECT public.create_session_login(:token_hash, :owner_id)"),
        {"token_hash": _hash_token(token), "owner_id": owner_id},
    )
    return token


def _get_new_token() -> str:
    return token_urlsafe()
