from fastapi import APIRouter, Depends, Response, Cookie
from rag_app.api._helpers import (
    _create_new_session,
    _get_new_token,
    _hash_token,
    _hash_password,
    _verify_password,
    _DUMMY_HASH,
)
from rag_app.config import get_settings

from uuid import UUID
from typing import Annotated
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from rag_app.api.deps import get_db_session, validate_session
from rag_app.exceptions import UsernameAlreadyExists, LoginUnsuccessful, InvalidSession

from sqlalchemy import text


class Credentials(BaseModel):
    # Max lengths bound argon2's work per request (DoS guard); no strength policy here.
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=128)


router = APIRouter()


@router.post("/register")
async def register(
    credentials: Credentials,
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> str:
    try:
        res = await db_session.execute(
            text("SELECT public.registration(:username, :password_hash);"),
            {
                "username": credentials.username,
                "password_hash": await _hash_password(credentials.password),
            },
        )
        val = res.scalar_one()
        if val is None:
            raise UsernameAlreadyExists(
                f"Username {credentials.username} already exists."
            )
    # for the race condition
    except IntegrityError:
        raise UsernameAlreadyExists(f"Username {credentials.username} already exists.")
    return f"Registration successful. Welcome {credentials.username}!"


@router.post("/login")
async def login(
    credentials: Credentials,
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    response: Response,
) -> str:
    res = await db_session.execute(
        text("SELECT * FROM public.login_check(:username)"),
        {"username": credentials.username},
    )
    rows = res.first()
    if rows is None:
        # Verify against a throwaway hash so a missing username costs the same as a real
        # one, then fail with the same message — no message or timing enumeration oracle.
        await _verify_password(_DUMMY_HASH, credentials.password)
        raise LoginUnsuccessful("Login unsuccessful.")
    if not await _verify_password(rows.password_hash, credentials.password):
        raise LoginUnsuccessful("Login unsuccessful.")
    token = await _create_new_session(rows.owner_id, db_session)
    response.set_cookie(
        "session_token",
        token,
        max_age=get_settings().cookie_expire,
        httponly=True,
        samesite="lax",
        secure=get_settings().secure,
    )
    return f"Login successful. Welcome {credentials.username}"


@router.post("/anonymous_login")
async def anonymous_login(
    db_session: Annotated[AsyncSession, Depends(get_db_session)], response: Response
) -> str:
    token = _get_new_token()
    await db_session.execute(
        text("SELECT public.anonymous_mint(:token_hash)"),
        {"token_hash": _hash_token(token)},
    )
    response.set_cookie(
        "session_token",
        token,
        max_age=get_settings().cookie_expire,
        httponly=True,
        samesite="lax",
        secure=get_settings().secure,
    )
    return "Anonymous login successful. Welcome!"


@router.post("/logout")
async def logout(
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    response: Response,
    token: Annotated[str | None, Cookie(alias="session_token")] = None,
) -> str:
    if token is None:
        return "You have been logged out. - None"
    await db_session.execute(
        text("SELECT public.logout(:token_hash)"), {"token_hash": _hash_token(token)}
    )
    response.delete_cookie("session_token")
    return "You have been logged out."


@router.post("/logout_everywhere")
async def logout_everywhere(
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    owner_id: Annotated[UUID, Depends(validate_session)],
    response: Response,
    token: Annotated[str | None, Cookie(alias="session_token")] = None,
) -> str:
    if token is None:
        return "You have been logged out everywhere."
    await db_session.execute(
        text("SELECT public.logout_everywhere(:owner_id)"), {"owner_id": owner_id}
    )
    response.delete_cookie("session_token")
    return "You have been logged out everywhere."


@router.post("/delete_account")
async def delete_account(
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    owner_id: Annotated[UUID | None, Depends(validate_session)],
    response: Response,
) -> str:
    if owner_id is None:
        raise InvalidSession()
    await db_session.execute(
        text("SELECT public.delete_account(:owner_id)"), {"owner_id": owner_id}
    )
    response.delete_cookie("session_token")
    return "Your account has been successfully deleted."
