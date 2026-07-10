import pytest
from rag_app.db.engine import make_engine, make_sessionmaker
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from rag_app.db.base import Base
from rag_app.stores.document_store import DocStore
from rag_app.stores.pg_vector_store import PgVectorStore
from rag_app.stores.chunk_store import ChunkStore
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


# The vector store is now stateless: it takes a caller-owned session per method,
# so no session_maker is needed to construct it.
@pytest.fixture
def vec_store():
    return PgVectorStore()


@pytest.fixture
def pg_vector_store():
    return PgVectorStore()


@pytest.fixture(scope="session")
async def setup_schema(engine):
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


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


@pytest.fixture
def db_tests(setup_schema, truncate):
    pass


@pytest.fixture
async def new_session(engine):
    @asynccontextmanager
    async def _make():
        async with AsyncSession(engine, expire_on_commit=False) as s:
            yield s

    return _make
