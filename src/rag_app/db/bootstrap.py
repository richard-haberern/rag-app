from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

import rag_app.models  # noqa: F401  -- registers all models on Base.metadata
from rag_app.db.base import Base
from rag_app.models.chunk import Chunk
from rag_app.models.document import Document
from rag_app.models.vector import Vector


async def init_db(engine: AsyncEngine) -> None:
    """Create the whole schema: the pgvector extension and the documents, chunks and
    vectors tables. Everything lives in one Postgres datastore now.

    CREATE EXTENSION requires sufficient DB privileges (fine in the local container; a
    deployment-time concern once it leaves it). Alembic migrations are deferred (see
    DECISIONS.md); this is the MVP bootstrap - idempotent, safe per boot.
    """
    # .begin() instead of .connect() - creates the transaction - auto commits / rollback at the end
    # create_all has to be sync
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(
            Base.metadata.create_all,
            tables=[
                Base.metadata.tables[Document.__tablename__],
                Base.metadata.tables[Chunk.__tablename__],
                Base.metadata.tables[Vector.__tablename__],
            ],
        )


async def drop_db(engine: AsyncEngine) -> None:
    """No Alembic yet need to drop and recrete the databse when the
    tables change.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
