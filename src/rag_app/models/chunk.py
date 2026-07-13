from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from rag_app.db.base import Base

# for circular-import risk
if TYPE_CHECKING:
    from rag_app.models.document import Document
    from rag_app.models.vector import Vector


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "position", name="uq_chunk_document_position"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    content: Mapped[str]
    position: Mapped[int]
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("stored_documents.id", ondelete="CASCADE")
    )

    original_document: Mapped["Document"] = relationship(back_populates="chunks")
    vector: Mapped["Vector"] = relationship(
        back_populates="original_chunk",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"Chunk(id={self.id!r}, position={self.position!r})"
