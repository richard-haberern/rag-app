from rag_app.config import get_settings
from rag_app.llm import LLMClient
from rag_app.llm.prompter import build_prompt
from rag_app.services.retriever import RetrievalService


class AnswerService:
    # DI
    def __init__(self, llm_client: LLMClient, retriever: RetrievalService) -> None:
        self.llm_client = llm_client
        self.retriever = retriever
    async def get_answer(self, query: str, k: int | None = None) -> str:
        # here we have to give answer if the context window is empty
        if k is None:
            k = get_settings().retrieval_top_k
        top_k = await self.retriever.search_topk_chunks(query, k)
        if not top_k:
            return "There is not enough context to generate a good answer."
        prompt = build_prompt(query, top_k)
        return await self.llm_client.generate(prompt)
