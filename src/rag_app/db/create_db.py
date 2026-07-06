from asyncio import run

from rag_app.config import get_settings
from rag_app.db.bootstrap import init_db, init_pgvector
from rag_app.db.engine import make_engine


async def _create() -> None:
    engine = make_engine()
    try:
        await init_db(engine)  # documents + chunks, always
        if get_settings().vector_db == "Postgres":
            await init_pgvector(engine)  # extension + vectors table, PG-backend only
    finally:
        await engine.dispose()


def main() -> None:
    run(_create())


if __name__ == "__main__":
    main()
