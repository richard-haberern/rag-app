from os.path import isfile
from uuid import UUID

import aiofiles
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, exists

from rag_app.models.document import Document
from rag_app.schemas import DocumentDTO


class DocStore:

    async def add_document(self, session: AsyncSession, document: DocumentDTO) -> None:
        session.add(
            Document(
                id=document.id,
                filename=document.filename,
                path_raw_content=document.path_raw_content,
                content_hash=document.content_hash,
                doc_metadata=document.doc_metadata
            )
        )

    async def get_document(self, session: AsyncSession, id: UUID) -> DocumentDTO:
        doc = await session.get(Document, id)
        if doc is None:
            raise ValueError(f"Document {id} doesn't exist")
        return DocumentDTO(
            id=doc.id,
            filename=doc.filename,
            path_raw_content=doc.path_raw_content,
            content_hash=doc.content_hash,
            doc_metadata=doc.doc_metadata
        )

    async def get_document_content(self, session: AsyncSession, id: UUID) -> str:
        doc = await self.get_document(session, id)
        return await get_file_content_from_path(doc.path_raw_content)

    async def remove_document(self, session: AsyncSession, id: UUID) -> None:
        doc = await session.get(Document, id)
        if doc is None:
            raise ValueError(f"Document {id} doesn't exist")
        await session.delete(doc)

    async def exists(self, session: AsyncSession, doc: DocumentDTO) -> bool:
        res = await session.execute(
            select(exists().where(Document.content_hash == doc.content_hash))
        )
        return bool(res.scalar())


async def get_file_content_from_path(path: str) -> str:
        if not isfile(path):
            raise OSError(f"File at {path!r} doesn't exist")
        async with aiofiles.open(path, mode="r") as f:
            return await f.read()
