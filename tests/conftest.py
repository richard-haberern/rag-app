from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from rag_app.db.engine import make_engine, make_sessionmaker
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from rag_app.db.base import Base
from rag_app.stores.document_store import DocStore
from rag_app.stores.pg_vector_store import PgVectorStore
from rag_app.stores.chunk_store import ChunkStore
from rag_app.config import Settings

# Reuse the app's own crypto helpers so tests hash tokens/passwords exactly as
# production does -- one source of truth, no chance of the test path drifting.
from rag_app.api._helpers import _hash_token, _get_new_token, _hash_password
from tests.fakes import FakeTokenizer, FakeEmbedder, make_mock_llm_client
from contextlib import asynccontextmanager


@dataclass(frozen=True)
class Identity:
    """A test tenant: the owner_id RLS scopes on, plus the raw (unhashed) session
    token -- usable as the `session_token` cookie value if HTTP tests are added
    later. `username`/`password` are set only for logged-in identities."""

    owner_id: UUID
    token: str
    username: str | None = None
    password: str | None = None


@pytest.fixture(scope="session")
async def engine(settings_session):
    engine = make_engine(settings_session.test_sqlalchemy_url)
    yield engine
    await engine.dispose()


@pytest.fixture
def session_maker(engine):
    # Same factory the app uses (expire_on_commit=False); the concrete stores own
    # their own sessions/transactions through it.
    return make_sessionmaker(engine)


@pytest.fixture
async def session(engine):
    session = AsyncSession(engine, expire_on_commit=False)
    yield session
    await session.close()


@pytest.fixture
async def truncate(session: AsyncSession):
    tables = ", ".join(Base.metadata.tables)
    await session.execute(text(f"TRUNCATE {tables} CASCADE"))
    await session.commit()
    yield


@pytest.fixture
def doc_store():
    return DocStore()


@pytest.fixture
def chunk_store():
    return ChunkStore()


# The vector store is now stateless: it takes a caller-owned session per method,
# so no session_maker is needed to construct it.
@pytest.fixture
def vec_store():
    return PgVectorStore()


@pytest.fixture
def pg_vector_store():
    return PgVectorStore()


# Function-scoped and mutable: a test may tweak fields (e.g. chunk_size) without
# leaking into other tests.
@pytest.fixture
def settings():
    return Settings()


# Separate session-scoped settings for infra fixtures. `engine` is session-scoped,
# and pytest forbids a higher-scoped fixture depending on a lower-scoped one, so it
# can't use the function-scoped `settings` above. This instance is never mutated.
@pytest.fixture(scope="session")
def settings_session():
    return Settings()


@pytest.fixture
def fake_tokenizer():
    return FakeTokenizer()


@pytest.fixture
def fake_embedder(fake_tokenizer, settings_session):
    return FakeEmbedder(
        fake_tokenizer, settings_session.embed_dim, settings_session.chunk_size
    )


# Yields a factory: call _make(handler) with an httpx MockTransport handler to get a
# real LLMClient backed by canned responses. All clients created in a test are closed
# at teardown.
@pytest.fixture
async def make_llm_client():
    clients = []

    def _make(handler):
        client, llm = make_mock_llm_client(handler)
        clients.append(client)
        return llm

    yield _make
    for client in clients:
        await client.aclose()


# Schema (extension + tables + RLS + policies + grants) is provisioned out-of-band by
# `alembic upgrade head` against rag_test before the suite runs. This
# fixture only resets data between tests.
@pytest.fixture
def db_tests(truncate):
    pass


@pytest.fixture
async def new_session(engine):
    @asynccontextmanager
    async def _make():
        async with AsyncSession(engine, expire_on_commit=False) as s:
            yield s

    return _make


# --- RLS-aware fixtures: connect as app_user (non-superuser), so tenant isolation is
# actually enforced. Use these to test owner_isolation behavior; use `session` for
# everything else. Shape mirrors api/deps.py's set_guc_rw/set_guc_ro exactly: one
# transaction per unit of work (session_maker.begin()), GUC set transaction-locally
# for it -- no assumption that SQLAlchemy reuses the same pooled connection across
# multiple commits, unlike a longer-lived session.


@pytest.fixture(scope="session")
async def app_engine(settings_session):
    engine = make_engine(settings_session.test_app_sqlalchemy_url)
    yield engine
    await engine.dispose()


@pytest.fixture
def app_session(app_engine):
    """Factory: `async with app_session(owner_id) as s` opens one transaction as
    app_user with app.owner_id set transaction-locally for it (mirrors set_guc_rw).
    `async with app_session() as s` with no owner_id leaves the GUC unset (mirrors
    set_guc_ro with no resolved owner) -- the fail-closed path, directly testable."""
    session_maker = make_sessionmaker(app_engine)

    @asynccontextmanager
    async def _make(owner_id: UUID | None = None):
        async with session_maker.begin() as s:
            if owner_id is not None:
                await s.execute(
                    text("SELECT set_config('app.owner_id', :id, true)"),
                    {"id": str(owner_id)},
                )
            yield s

    return _make


# --- Identity factories: mint a real owner (+ session) through the same SQL auth
# functions the endpoints use, so FK constraints, RLS and session validation behave
# exactly like production. Each returns an async factory; call it more than once per
# test for distinct tenants, e.g. `a, b = await anonymous(), await anonymous()`.


@pytest.fixture
def anonymous(app_session):
    """Factory for an anonymous tenant: owner (expires_at = now()+30d) + session, no
    users row. Mirrors POST /anonymous_login. Runs via an app_user transaction with no
    owner GUC; anonymous_mint is SECURITY DEFINER so it can still write owners/sessions."""

    async def _make() -> Identity:
        token = _get_new_token()
        async with app_session() as s:
            res = await s.execute(
                text("SELECT public.anonymous_mint(:token_hash)"),
                {"token_hash": _hash_token(token)},
            )
            owner_id = res.scalar_one()
        return Identity(owner_id=owner_id, token=token)

    return _make


@pytest.fixture
def logged_in(app_session):
    """Factory for a registered tenant: owner (expires_at NULL) + users row + login
    session. Mirrors POST /register followed by POST /login. Username defaults to a
    unique value; override username/password to test specific-credential flows."""

    async def _make(
        username: str | None = None, password: str = "test-password-123"
    ) -> Identity:
        username = username or f"user-{uuid4().hex[:12]}"
        pw_hash = await _hash_password(password)
        token = _get_new_token()
        async with app_session() as s:
            res = await s.execute(
                text("SELECT public.registration(:username, :password_hash)"),
                {"username": username, "password_hash": pw_hash},
            )
            owner_id = res.scalar_one()  # None only if username already taken
            await s.execute(
                text("SELECT public.create_session_login(:token_hash, :owner_id)"),
                {"token_hash": _hash_token(token), "owner_id": owner_id},
            )
        return Identity(
            owner_id=owner_id, token=token, username=username, password=password
        )

    return _make


@pytest.fixture
def expired_session(session):
    """Factory for an owner whose session is already expired. No SQL function mints an
    expired session, so this INSERTs directly with a past expires_at via the superuser
    `session` (app_user has no direct write on owners/sessions). Use it to test that
    validate_session rejects expired sessions and that sweep_sessions removes them.
    Pass owner_expired=True to also backdate the owner so sweep_owners collects it."""

    async def _make(owner_expired: bool = False) -> Identity:
        token = _get_new_token()
        # Fixed literal chosen in code, never caller input -- no injection surface.
        owner_expires = (
            "pg_catalog.now() - interval '1 day'" if owner_expired else "NULL"
        )
        res = await session.execute(
            text(
                f"INSERT INTO owners (expires_at) VALUES ({owner_expires}) RETURNING id"
            )
        )
        owner_id = res.scalar_one()
        await session.execute(
            text(
                "INSERT INTO sessions (token_hash, owner_id, expires_at) "
                "VALUES (:h, :oid, pg_catalog.now() - interval '1 day')"
            ),
            {"h": _hash_token(token), "oid": owner_id},
        )
        await session.commit()
        return Identity(owner_id=owner_id, token=token)

    return _make
