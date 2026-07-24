from rag_app.config import get_settings
from rag_app.llm import LLMClient
from rag_app.llm.prompter import build_prompt
from rag_app.services.retriever import RetrievalService
from sqlalchemy.ext.asyncio import AsyncSession
from rag_app.schemas import QueryAnswer, Citation
import re

def strip_invalid_markers(content: str, n: int) -> str:
    return re.sub(r"\[\[(\d+)\]\]", 
                  lambda m: m.group(0) if 1 <= int(m.group(1)) <= n else "", 
                  content)

class AnswerService:
    # DI
    def __init__(self, llm_client: LLMClient, retriever: RetrievalService) -> None:
        self.llm_client = llm_client
        self.retriever = retriever

    async def get_answer(
        self,
        session: AsyncSession,
        query: str,
        k: int | None = None,
        threshold: float | None = None,
    ) -> QueryAnswer:
        # here we have to give answer if the context window is empty
        if k is None:
            k = get_settings().retrieval_top_k
        if threshold is None:
            threshold = get_settings().retrieval_threshold
        top_k = await self.retriever.search_topk_chunks(session, query, k, threshold)
        if not top_k:
            return QueryAnswer(content="There is not enough context to generate a good answer.", chunks=[])
        numbered = [Citation(marker=i, content=chunk.content, document_id=chunk.document_id, filename=name, position=chunk.position) for i, (chunk, name) in enumerate(top_k, 1)]
        prompt = build_prompt(query, [(cit.marker, cit.content) for cit in numbered])
        answer = strip_invalid_markers(await self.llm_client.generate(prompt), len(top_k))
        return QueryAnswer(content=answer, chunks=numbered)
