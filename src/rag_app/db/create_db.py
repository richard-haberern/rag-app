from asyncio import run

from rag_app.db.bootstrap import init_db
from rag_app.db.engine import make_engine


async def _create() -> None:
    engine = make_engine()
    try:
        await init_db(engine)  # extension + documents, chunks, vectors tables
    finally:
        await engine.dispose()


def main() -> None:
    run(_create())


if __name__ == "__main__":
    main()
