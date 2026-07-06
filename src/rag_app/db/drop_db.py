from rag_app.db.bootstrap import drop_db
from asyncio import run
from rag_app.db.engine import make_engine


def main() -> None:
    engine = make_engine()
    run(drop_db(engine))
    run(engine.dispose())


if __name__ == "__main__":
    main()
