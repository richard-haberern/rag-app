from typing import TYPE_CHECKING
from uuid import UUID
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from rag_app.db.base import Base

if TYPE_CHECKING:
    from rag_app.models.document import Document


class Owner(Base):
    __tablename__ = "owners"

    id: Mapped[UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    # Server-side default so every row is stamped by the DB clock (uniform, tz-aware); the
    # app never sends this value. created_at + TTL is the sweep's expiry test.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)

    documents: Mapped[list["Document"]] = relationship(
        back_populates="owner",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
