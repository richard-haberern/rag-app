from typing import TYPE_CHECKING
from uuid import UUID

from pgvector.sqlalchemy import Vector as PgVector
from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from rag_app.config import get_settings
from rag_app.db.base import Base
from rag_app.schemas import Embedding

if TYPE_CHECKING:
    from rag_app.models.chunk import Chunk

_EMBED_DIM = get_settings().embed_dim


class Vector(Base):
    __tablename__ = "vectors"

    chunk_id: Mapped[UUID] = mapped_column(
        ForeignKey("chunks.id", ondelete="CASCADE"), primary_key=True
    )
    content: Mapped[Embedding] = mapped_column(PgVector(_EMBED_DIM))

    original_chunk: Mapped["Chunk"] = relationship(back_populates="vector")

    def __repr__(self) -> str:
        return f"Vector(chunk_id={self.chunk_id!r})"
