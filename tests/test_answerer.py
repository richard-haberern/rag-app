"""AnswerService.get_answer — the "no retrievable context" branch.

When retrieval comes back empty, get_answer must short-circuit to its canned message and never
call the LLM. Driven with the FakeEmbedder double + an empty DB, and an httpx handler that fails
the test if the LLM is ever hit.
"""

import httpx

from rag_app.chunkings.chunker import Chunker
from rag_app.services.answerer import AnswerService
from rag_app.services.retriever import RetrievalService
from rag_app.llm.llm_client import LLMClient


_NO_CONTEXT_MSG = "There is not enough context to generate a good answer."


async def test_get_answer_no_context_skips_llm(
    engine,
    doc_store,
    chunk_store,
    pg_vector_store,
    fake_embedder,
    fake_tokenizer,
    new_session,
    db_tests,
):
    def exploding_handler(req: httpx.Request) -> httpx.Response:
        raise AssertionError("LLM must not be called when retrieval is empty")

    client = httpx.AsyncClient(transport=httpx.MockTransport(exploding_handler))
    llm = LLMClient(model="fake", base_url="http://test", client=client)

    chunker = Chunker(fake_tokenizer, 20, 5)
    retriever = RetrievalService(
        chunk_store, pg_vector_store, doc_store, fake_embedder, chunker
    )
    answerer = AnswerService(llm, retriever)

    try:
        # Empty DB (db_tests truncated) -> search returns no chunks -> canned message, no LLM call.
        # with treshold added will test with non-empty db - TODO
        async with new_session() as s:
            resp = await answerer.get_answer(s, "What is the meaning of life?", k=3)
    finally:
        await client.aclose()

    assert resp == _NO_CONTEXT_MSG
