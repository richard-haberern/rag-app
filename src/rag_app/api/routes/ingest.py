from fastapi import APIRouter, status
from fastapi import Depends

from pydantic import BaseModel
from typing import Annotated
from uuid import uuid4, UUID
from hashlib import sha256

from rag_app.api.deps import get_ingestor, set_guc, validate_session
from rag_app.services.ingestor import IngestionService

from sqlalchemy.ext.asyncio import AsyncSession
from rag_app.schemas import DocumentDTO


# virtual document for v1. A path, if relevant, goes in metadata — the service no longer
# reads from the filesystem; content arrives in the request body.
class DocumentRequest(BaseModel):
    content: str
    filename: str
    metadata: dict = {}


router = APIRouter()


@router.post("/store")
async def store_document(
    document: DocumentRequest,
    ingestor: Annotated[IngestionService, Depends(get_ingestor)],
    session: Annotated[AsyncSession, Depends(set_guc)],
    owner_id: Annotated[UUID, Depends(validate_session)],
) -> UUID:
    doc_id = uuid4()
    await ingestor.store_document(
        session,
        DocumentDTO(
            id=doc_id,
            filename=document.filename,
            content_hash=sha256(document.content.encode()).hexdigest(),
            content=document.content,
            doc_metadata=document.metadata,
            owner_id=owner_id,
        ),
    )
    return doc_id


@router.delete("/delete/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_document(
    doc_id: UUID,
    ingestor: Annotated[IngestionService, Depends(get_ingestor)],
    session: Annotated[AsyncSession, Depends(set_guc)],
) -> None:
    await ingestor.remove_document(session, doc_id)
