from typing import Any

import httpx
from rag_app.exceptions import LLMBadAnswer, LLMError


class LLMClient:
    """Concrete Gemini (generateContent) client over raw httpx.

    Swappable seam for v1 = the `generate(prompt) -> str` method; no ABC/Protocol yet. The
    AsyncClient is injected and only borrowed: this class never configures or closes it.
    build_llm_client is what wires auth (x-goog-api-key) and timeout onto the client, so config
    stays out of here; whoever created the client owns its lifecycle and closes it.
    """

    def __init__(self, model: str, base_url: str, client: httpx.AsyncClient) -> None:
        # rstrip: a trailing slash in LLM_BASE_URL would produce `.../models//model:generateContent`
        # and a 404 reported as a generic upstream failure. Normalised here, not in the factory,
        # because tests construct LLMClient directly and bypass it.
        self._url = f"{base_url.rstrip('/')}/{model}:generateContent"
        self._client = client

    async def generate(self, prompt: str) -> str:
        req_body = {"contents": [{"parts": [{"text": prompt}]}]}
        # The client is borrowed, so its owner can close it before we're done with it (shutdown
        # ordering). httpx raises a bare RuntimeError for that, which is not an HTTPError and would
        # escape as an opaque 500. Checked rather than caught: `except RuntimeError` would also
        # swallow real bugs. Racy if the owner closes mid-flight; covers the ordering case.
        if self._client.is_closed:
            raise LLMError("LLM client is closed")
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
        # A 200 carrying a non-JSON body (gateway HTML, truncated response) raises
        # json.JSONDecodeError — a ValueError, so neither branch above catches it. Same 502
        # treatment: it's a broken upstream, not the model declining to answer.
        try:
            data = resp.json()
        except ValueError as exc:
            raise LLMError("LLM response was not JSON") from exc
        return self._extract_text(data)

    @staticmethod
    def _extract_text(data: dict[str, Any]) -> str:
        # Gemini can return 200 with no usable candidate (safety block / empty), so the happy-path
        # walk would raise an opaque KeyError/IndexError. Fail with something legible instead; the
        # caller (answerer) decides what to show the user on a missing answer.
        #
        # The message is deliberately static: AppError messages are rendered verbatim into the
        # response body, and `data` can carry promptFeedback, model internals and partial candidate
        # text — which, since the prompt is built from retrieved chunks, is the user's own document
        # content. TypeError covers a payload that isn't dict-shaped at all, despite the annotation.
        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMBadAnswer() from exc
        if not isinstance(text, str):
            raise LLMBadAnswer()
        return text
