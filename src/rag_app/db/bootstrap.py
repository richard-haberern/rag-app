from sqlalchemy import text

import rag_app.models  # noqa: F401  -- registers all models on Base.metadata
from rag_app.db.base import Base
from rag_app.db.engine import make_engine


async def init_db() -> None:
    """Create the pgvector extension and all tables.

    CREATE EXTENSION requires sufficient DB privileges. Alembic migrations are deferred
    (see DECISIONS.md); this is the MVP bootstrap.
    """
    # .begin() instead of .connect() - creates the transaction - auto commits / rollback at the end
    # create_all has to be sync
    engine = make_engine()
    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.run_sync(Base.metadata.create_all)
    finally:
        await engine.dispose()

