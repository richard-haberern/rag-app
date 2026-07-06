from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from typing import Literal


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # DB connection: only DB_PASSWORD is required; the rest default to the local dev
    # container. Kept optional so models (which only need embed_dim) import without it.
    # If we need just the embed_dim etc. and don't want to do anything with the database
    # no need for password
    db_user: str | None = None
    db_password: str | None = None
    db_password_test: str | None = None
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str | None = None
    db_name_test: str | None = None
    # Optional full override; if set, takes precedence over the DB_* parts above.
    database_url: str | None = None

    # ChromaDB settings
    chroma_host: str = "localhost"
    chroma_port: int = 8000
    # How long the app/tests wait for the Chroma server to accept connections
    # before giving up. The distroless chroma image ships no curl/wget/python, so a
    # compose healthcheck is impossible; readiness is enforced app-side (connect()).
    chroma_connect_retries: int = 30
    chroma_connect_delay: float = 1.0  # seconds between attempts

    embed_model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    embed_dim: int = 384
    embed_device: str = "cpu"
    embed_batch_size: int = 32

    # Chunking. chunk_size is the desired token window; None means "use the model's full
    # content window" (max_content_tokens). An explicit value is validated against that ceiling
    # in build_chunker, so we never assume a specific model's limit here.
    chunk_size: int | None = None
    chunk_overlap_ratio: float = 0.12

    # Retrieval. Default number of top chunks and threshold
    # for cosine distance for a query when the caller doesn't specify.
    retrieval_top_k: int = 5
    retrieval_threshold: float = 0.7
    # LLM (generation). Endpoint is base_url + model so the model can be swapped without rewriting a
    # full URL. llm_api_key is required only when actually calling the LLM (like db_password for the
    # DB), so modules that don't generate still import. llm_timeout: httpx defaults to 5s, far too
    # short for generation.
    llm_api_key: str | None = None
    llm_model: str = "gemini-2.5-flash"
    llm_base_url: str = "https://generativelanguage.googleapis.com/v1beta/models"
    llm_timeout: float = 60.0

    vector_db: Literal["ChromaDB", "Postgres"] = "ChromaDB"

    @property
    def sqlalchemy_url(self) -> str:
        if self.database_url:
            return self.database_url
        if self.db_password is None:
            raise ValueError("DB_PASSWORD is required to build the database URL")
        return (
            f"postgresql+asyncpg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def sqlalchemy_url_test(self) -> str:
        # Deliberately ignores database_url: the test URL must be built from the
        # explicit DB_*_TEST parts so the suite's TRUNCATE/DROP can never alias prod
        # via a stray DATABASE_URL. (Flag for DECISIONS.md.)
        if self.db_password_test is None:
            raise ValueError(
                "DB_PASSWORD_TEST is required to build the test database URL"
            )
        if self.db_name_test is None:
            raise ValueError("DB_NAME_TEST is required to build the test database URL")
        return (
            f"postgresql+asyncpg://{self.db_user}:{self.db_password_test}"
            f"@{self.db_host}:{self.db_port}/{self.db_name_test}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
