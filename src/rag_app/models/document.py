from typing import (
    TYPE_CHECKING,
    Any
    )
from uuid import UUID, uuid4

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from rag_app.db.base import Base


if TYPE_CHECKING:
    from rag_app.models.chunk import Chunk


class Document(Base):
    __tablename__ = "stored_documents"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    filename: Mapped[str]
    path_raw_content: Mapped[str]
    content_hash: Mapped[str] = mapped_column(unique=True, nullable=False)
    # 'metadata' is reserved on declarative classes (it's the MetaData registry), so the
    # attribute is doc_metadata while the DB column stays "metadata".
    doc_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)

    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="original_document",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"Document(id={self.id!r}, filename={self.filename!r})"
