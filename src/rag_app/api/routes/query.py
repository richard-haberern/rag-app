from fastapi import APIRouter
from fastapi import Depends

from typing import Annotated, Sequence
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


# Metadata-only view for listing stored documents: deliberately omits `content` so a
# corpus-wide listing doesn't ship every document's full text.
class DocumentSummary(BaseModel):
    filename: str
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


@router.get("/stored_documents/ids")
async def get_stored_documents_ids(
    retriever: Annotated[RetrievalService, Depends(get_retriever)],
) -> Sequence[UUID]:
    return await retriever.get_stored_documents_ids()


@router.get("/stored_documents/metadata")
async def get_stored_documents_metadata(
    retriever: Annotated[RetrievalService, Depends(get_retriever)],
) -> Sequence[DocumentSummary]:
    docDTOs = await retriever.get_stored_documents_DTOs()
    return [
        DocumentSummary(
            filename=d.filename,
            doc_id=d.id,
            doc_metadata=d.doc_metadata,
        )
        for d in docDTOs
    ]
