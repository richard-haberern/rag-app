from rag_app.db.bootstrap import drop_db
from asyncio import run


def main() -> None:
    run(drop_db())


if __name__ == "__main__":
    main()
