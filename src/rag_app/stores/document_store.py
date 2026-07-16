from uuid import UUID, uuid4

from typing import Sequence

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from rag_app.models.document import Document

from rag_app.schemas import DocumentDTO
from rag_app.exceptions import DocumentNotFound


class DocStore:
    async def add_document(self, session: AsyncSession, document: DocumentDTO) -> None:
        session.add(
            Document(
                id=document.id,
                filename=document.filename,
                content=document.content,
                content_hash=document.content_hash,
                doc_metadata=document.doc_metadata,
                owner_id=document.owner_id
            )
        )

    async def get_document(self, session: AsyncSession, id: UUID) -> DocumentDTO:
        doc = await session.get(Document, id)
        if doc is None:
            raise DocumentNotFound(f"Document {id} doesn't exist")
        return DocumentDTO(
            id=doc.id,
            filename=doc.filename,
            content_hash=doc.content_hash,
            content=doc.content,
            doc_metadata=doc.doc_metadata,
            owner_id=doc.owner_id
        )

    async def get_document_content(self, session: AsyncSession, id: UUID) -> str:
        doc = await session.get(Document, id)
        if doc is None:
            raise DocumentNotFound(f"Document {id} doesn't exist")
        return doc.content

    async def get_stored_documents(
        self, session: AsyncSession
    ) -> Sequence[DocumentDTO]:
        result = await session.execute(select(Document.id, Document.filename, Document.doc_metadata))
        return [
            DocumentDTO(row.id, row.filename, "", "", uuid4(), row.doc_metadata)
            for row in result.all()
        ]

    async def get_stored_documents_ids(self, session: AsyncSession) -> Sequence[UUID]:
        # need to add created_at so we can order by that
        result = await session.execute(select(Document.id).order_by(Document.id))
        return result.scalars().all()

    async def remove_document(self, session: AsyncSession, id: UUID) -> None:
        doc = await session.get(Document, id)
        if doc is None:
            raise DocumentNotFound(f"Document {id} doesn't exist")
        await session.delete(doc)

    async def exists(self, session: AsyncSession, doc: DocumentDTO) -> bool:
        res = await session.execute(
            select(exists().where(Document.content_hash == doc.content_hash))
        )
        return bool(res.scalar())
