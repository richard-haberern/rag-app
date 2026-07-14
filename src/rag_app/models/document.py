from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from rag_app.db.base import Base


if TYPE_CHECKING:
    from rag_app.models.chunk import Chunk
    from rag_app.models.user import User


class Document(Base):
    __tablename__ = "documents"
    # content_hash dedup is per-tenant, not global: two tenants may legitimately store the
    # same content
    __table_args__ = (
        UniqueConstraint("owner_id", "content_hash", name="uq_document_owner_hash"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    filename: Mapped[str]
    # Original document text, stored verbatim. Also lives split across chunks; kept here so
    # full-content reads are exact (joining chunks would duplicate overlap / drop whitespace).
    content: Mapped[str]
    content_hash: Mapped[str] = mapped_column(nullable=False)
    # 'metadata' is reserved on declarative classes (it's the MetaData registry), so the
    # attribute is doc_metadata while the DB column stays "metadata".
    doc_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, default=dict
    )
    # Tenant owner. FK -> users.id ON DELETE CASCADE is what makes the sweep purge a user's
    # documents (and, in turn, their chunks/vectors); the cascade is an FK action, so it runs
    # even though RLS/FORCE is on. Indexed: the documents RLS policy and the cascade scan it.
    owner_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    owner: Mapped["User"] = relationship(back_populates="documents")

    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="original_document",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"Document(id={self.id!r}, filename={self.filename!r})"
