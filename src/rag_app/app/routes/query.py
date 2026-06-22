from fastapi import APIRouter
from fastapi import Depends

from typing import Annotated
from pydantic import BaseModel
from uuid import UUID

from rag_app.app.deps import get_answerer

from rag_app.services.answerer import AnswerService

from rag_app.llm import LLMClient
from rag_app.stores.document_store import DocStore

router = APIRouter(prefix="/query")

class DocumentResponse(BaseModel):
    filename: str
    content: str
    doc_id: UUID
    doc_metadata: dict

class GenereateRequest(BaseModel):
    query: str

@router.post("/generate/")
async def generate_answer(q: GenereateRequest, answerer: Annotated[AnswerService, Depends(get_answerer)]) -> str:
    return await answerer.get_answer(q.query)

@router.get("/documents/{doc_id}")
async def get_document(doc_id: UUID, answerer: Annotated[AnswerService, Depends(get_answerer)]) -> DocumentResponse:
    doc_DTO = await answerer.get_document(doc_id)
    doc_content = await answerer.get_document_content(doc_id)
    return DocumentResponse(filename=doc_DTO.filename, content=doc_content, doc_id=doc_DTO.id, doc_metadata=doc_DTO.doc_metadata)