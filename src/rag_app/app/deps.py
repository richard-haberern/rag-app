from rag_app.services.answerer import AnswerService
from rag_app.services.ingestor import IngestionService
from rag_app.llm.llm_client import LLMClient

from fastapi import Request


def get_answerer(request: Request) -> AnswerService:
    return request.app.state.answerer

def get_ingestor(request: Request) -> IngestionService:
    return request.app.state.ingestor



