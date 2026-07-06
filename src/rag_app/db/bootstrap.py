from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

import rag_app.models  # noqa: F401  -- registers all models on Base.metadata
from rag_app.db.base import Base
from rag_app.models.chunk import Chunk
from rag_app.models.document import Document
from rag_app.models.vector import Vector


async def init_db(engine: AsyncEngine) -> None:
    """Create the relational schema: the documents and chunks tables.

    These always live in Postgres regardless of the vector backend. The pgvector extension
    and the vectors table are Postgres-vector-backend-only and created by init_pgvector.
    Alembic migrations are deferred (see DECISIONS.md); this is the MVP bootstrap.
    """
    # .begin() instead of .connect() - creates the transaction - auto commits / rollback at the end
    # create_all has to be sync
    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all,
            tables=[
                Base.metadata.tables[Document.__tablename__],
                Base.metadata.tables[Chunk.__tablename__],
            ],
        )


async def init_pgvector(engine: AsyncEngine) -> None:
    """Create the pgvector extension + the stored_vectors table. Postgres-backend only.

    CREATE EXTENSION requires sufficient DB privileges. Called only when Postgres is the
    chosen vector store; in Chroma mode neither the extension nor the table is touched.
    """
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(
            Base.metadata.create_all,
            tables=[Base.metadata.tables[Vector.__tablename__]],
        )


async def drop_db(engine: AsyncEngine) -> None:
    """No Alembic yet need to drop and recrete the databse when the
    tables change.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
