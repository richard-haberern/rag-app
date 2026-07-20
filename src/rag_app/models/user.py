from datetime import datetime

from rag_app.db.base import Base

from uuid import UUID


from sqlalchemy import func, ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column


class User(Base):
    __tablename__ = "users"
    owner_id: Mapped[UUID] = mapped_column(
        ForeignKey("owners.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    password_hash: Mapped[str] = mapped_column(nullable=False)
    username: Mapped[str] = mapped_column(unique=True, nullable=False)
