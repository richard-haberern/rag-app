from rag_app.db.bootstrap import init_db
from asyncio import run


def main() -> None:
    run(init_db())


if __name__ == "__main__":
    main()
