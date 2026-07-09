import httpx
from rag_app.exceptions import LLMBadAnswer, LLMError


class LLMClient:
    """Concrete Gemini (generateContent) client over raw httpx.

    Swappable seam for v1 = the `generate(prompt) -> str` method; no ABC/Protocol yet. The
    AsyncClient is injected and only borrowed: LLMClient does not own, configure, or close it.
    Auth (x-goog-api-key) and timeout live on the client (wired by build_llm_client); whoever
    created the client owns its lifecycle and closes it.
    """

    def __init__(self, model: str, base_url: str, client: httpx.AsyncClient) -> None:
        self._url = f"{base_url}/{model}:generateContent"
        self._client = client

    async def generate(self, prompt: str) -> str:
        req_body = {"contents": [{"parts": [{"text": prompt}]}]}
        # Any upstream failure (4xx/5xx, timeout, connection drop) becomes an LLMError so it
        # surfaces as a 502, not an opaque 500. Report the status code only — str(exc) on a
        # status error embeds the Gemini URL, which shouldn't leak to the client.
        try:
            resp = await self._client.post(self._url, json=req_body)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise LLMError(f"LLM upstream returned {exc.response.status_code}") from exc
        except httpx.HTTPError as exc:
            raise LLMError("LLM request failed") from exc
        return self._extract_text(resp.json())

    @staticmethod
    def _extract_text(data: dict) -> str:
        # Gemini can return 200 with no usable candidate (safety block / empty), so the happy-path
        # walk would raise an opaque KeyError/IndexError. Fail with something legible instead; the
        # caller (answerer) decides what to show the user on a missing answer.
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMBadAnswer(f"LLM returned no usable answer: {data!r}") from exc
