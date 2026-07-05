from fastapi import APIRouter
from fastapi import Depends

from typing import Annotated
from pydantic import BaseModel
from uuid import UUID

from rag_app.api.deps import get_answerer
from rag_app.api.deps import get_retriever

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
