from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
    AsyncEngine,
)

from rag_app.config import get_settings


# factory function that exposes engine
def make_engine(url: str | None = None) -> AsyncEngine:
    if url is None:
        url = get_settings().sqlalchemy_url
    return create_async_engine(url, connect_args={"ssl": True})


# factory function that exposes the session_maker
# expire_on_commit=False: in async we must avoid implicit lazy-load I/O triggered by
# attribute access after commit (a refresh would emit SQL outside an awaited call).
def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
