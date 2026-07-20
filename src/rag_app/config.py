from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from pathlib import Path
from datetime import timedelta


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str | None = None
    app_database_url: str | None = None

    test_database_url: str | None = None
    test_app_database_url: str | None = None
    # asyncpg SSL toggle. Off for local/CI/test Postgres (no TLS); Neon and other
    # managed Postgres require it, so the deploy env sets DB_SSL=true.
    db_ssl: bool = False

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

    # Directory served at "/" by the static mount. Default resolves to the repo-root
    # static/ (works when run from the repo tree); Docker overrides via STATIC_DIR.
    static_dir: str = str(Path(__file__).resolve().parents[2] / "static")

    secure: bool = False
    # Anonymous-tenant identity lifetime. TTL is the server-side data-retention window (a
    # user row and its documents survive this long); cookie_expire is the browser cookie's
    # max_age in seconds. Keep them aligned so the cookie and the data expire together.
    TTL: timedelta = timedelta(days=30)
    cookie_expire: int = int(timedelta(days=30).total_seconds())

    sweep_token: str | None = None

    @property
    def sqlalchemy_url(self) -> str:
        if self.database_url is None:
            raise ValueError("DATABASE_URL has to be set to connect to the database")
        return self.database_url

    @property
    def test_sqlalchemy_url(self) -> str:
        if self.test_database_url is None:
            raise ValueError(
                "TEST_DATABASE_URL has to be set to connect to the database"
            )
        return self.test_database_url

    @property
    def app_sqlalchemy_url(self) -> str:
        if self.app_database_url is None:
            raise ValueError(
                "APP_DATABASE_URL is required to build the app_user database URL"
            )
        return self.app_database_url

    @property
    def test_app_sqlalchemy_url(self) -> str:
        if self.test_app_database_url is None:
            raise ValueError(
                "APP_DATABASE_URL_TEST is required to build the app_user test database URL"
            )
        return self.test_app_database_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
