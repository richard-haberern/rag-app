from rag_app.config import Settings, get_settings
from rag_app.llm.llm_client import LLMClient

from httpx import AsyncClient


def build_llm_client(
    client: AsyncClient, settings: Settings | None = None
) -> LLMClient:
    """Construct an LLMClient from Settings, configuring the injected AsyncClient.

    Single place that reads LLM config and enforces the api key is present. The client is injected
    (DI, testable) but bare; this wires the auth header + timeout onto it from Settings, so LLMClient
    stays free of config. Mirrors build_chunker. Caller owns the client's lifecycle (close).
    """
    settings = settings or get_settings()
    if settings.llm_api_key is None:
        raise ValueError("LLM_API_KEY is required to call the LLM")
    client.headers["x-goog-api-key"] = settings.llm_api_key
    client.timeout = settings.llm_timeout
    return LLMClient(settings.llm_model, settings.llm_base_url, client)
