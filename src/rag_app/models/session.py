from rag_app.db.base import Base

from uuid import UUID
from datetime import datetime
from sqlalchemy import DateTime, func, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    token_hash: Mapped[str] = mapped_column(unique=True, nullable=False)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("owners.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
