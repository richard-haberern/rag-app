from fastapi import APIRouter
from fastapi import Depends

from pydantic import BaseModel
from typing import Annotated
from uuid import uuid4
from hashlib import sha256

from rag_app.services.answerer import AnswerService
from rag_app.app.deps import get_answerer
from rag_app.app.deps import get_ingestor
from rag_app.services.ingestor import IngestionService
from rag_app.stores.document_store import get_file_content_from_path

from rag_app.schemas import DocumentDTO

# virtual document for v1
class DocumentRequest(BaseModel):
    content: str
    filename: str
    path: str
    metadata: dict = {}

router = APIRouter(prefix="/ingest")

@router.post("/store")
async def store_document(document: DocumentRequest, ingestor: Annotated[IngestionService, Depends(get_ingestor)]):
    doc_content = await get_file_content_from_path(document.path)
    await ingestor.store_document(
        DocumentDTO(
            id=uuid4(),
            filename=document.filename,
            path_raw_content=document.path,
            content_hash=sha256(doc_content.encode()).hexdigest(),
            doc_metadata=document.metadata,
        )
    )
