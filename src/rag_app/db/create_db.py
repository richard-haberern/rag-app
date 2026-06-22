from rag_app.db.bootstrap import init_db
from asyncio import run
from rag_app.config import get_settings


def main():
    run(init_db())

if __name__ == "__main__":
    main()