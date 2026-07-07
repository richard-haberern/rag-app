from fastapi import APIRouter
from fastapi import Depends

from typing import Annotated
from pydantic import BaseModel
from uuid import UUID

from rag_app.api.deps import get_answerer
from rag_app.api.deps import get_retriever

from rag_app.config import get_settings
from rag_app.services.answerer import AnswerService
from rag_app.services.retriever import RetrievalService

router = APIRouter(prefix="/query")


class DocumentResponse(BaseModel):
    filename: str
    content: str
    doc_id: UUID
    doc_metadata: dict


class GenerateRequest(BaseModel):
    query: str


@router.post("/generate")
async def generate_answer(
    q: GenerateRequest, answerer: Annotated[AnswerService, Depends(get_answerer)]
) -> str:
    return await answerer.get_answer(q.query)


# Additive endpoint for the demo frontend: exposes what retrieval found for a query.
# Same k/threshold defaults as AnswerService.get_answer; returns chunk contents in
# similarity order (scores never cross the service boundary).
@router.post("/retrieve")
async def retrieve_chunks(
    q: GenerateRequest, retriever: Annotated[RetrievalService, Depends(get_retriever)]
) -> list[str]:
    s = get_settings()
    return await retriever.search_topk_chunks(
        q.query, s.retrieval_top_k, s.retrieval_threshold
    )


@router.get("/documents/{doc_id}")
async def get_document(
    doc_id: UUID, retriever: Annotated[RetrievalService, Depends(get_retriever)]
) -> DocumentResponse:
    doc = await retriever.get_document(doc_id)
    return DocumentResponse(
        filename=doc.filename,
        content=doc.content,
        doc_id=doc.id,
        doc_metadata=doc.doc_metadata,
    )
