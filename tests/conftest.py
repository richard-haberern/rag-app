from uuid import UUID, uuid4

import pytest
from rag_app.db.engine import make_engine, make_sessionmaker
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from rag_app.db.base import Base
from rag_app.stores.document_store import DocStore
from rag_app.stores.pg_vector_store import PgVectorStore
from rag_app.stores.chunk_store import ChunkStore
from rag_app.stores.users_store import UserStore
from rag_app.config import Settings
from tests.fakes import FakeTokenizer, FakeEmbedder, make_mock_llm_client
from contextlib import asynccontextmanager


@pytest.fixture(scope="session")
async def engine(settings_session):
    engine = make_engine(settings_session.sqlalchemy_url_test)
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


@pytest.fixture
def user_store():
    return UserStore()


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
    engine = make_engine(settings_session.app_sqlalchemy_url_test)
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


@pytest.fixture
def tenant(app_session, user_store):
    """Factory: each call mints one fresh users row via UserStore.add_user in its own
    (no-owner) transaction -- api/_helpers.py's _mint, minus the cookie. Call it more
    than once per test for distinct tenants, e.g.
    `owner_a, owner_b = await tenant(), await tenant()`, to test cross-tenant
    isolation."""

    async def _make() -> UUID:
        new_id = uuid4()
        async with app_session() as s:
            await user_store.add_user(s, new_id)
        return new_id

    return _make
