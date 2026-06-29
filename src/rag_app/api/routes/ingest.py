from fastapi import APIRouter
from fastapi import Depends

from pydantic import BaseModel
from typing import Annotated
from uuid import uuid4, UUID
from hashlib import sha256

from rag_app.api.deps import get_ingestor
from rag_app.services.ingestor import IngestionService

from rag_app.schemas import DocumentDTO


# virtual document for v1. A path, if relevant, goes in metadata — the service no longer
# reads from the filesystem; content arrives in the request body.
class DocumentRequest(BaseModel):
    content: str
    filename: str
    metadata: dict = {}


router = APIRouter(prefix="/ingest")


@router.post("/store")
async def store_document(
    document: DocumentRequest,
    ingestor: Annotated[IngestionService, Depends(get_ingestor)],
) -> UUID:
    doc_id = uuid4()
    await ingestor.store_document(
        DocumentDTO(
            id=doc_id,
            filename=document.filename,
            content_hash=sha256(document.content.encode()).hexdigest(),
            content=document.content,
            doc_metadata=document.metadata,
        )
    )
    return doc_id
