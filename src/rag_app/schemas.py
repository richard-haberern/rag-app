from dataclasses import dataclass, field
from uuid import UUID
from typing import Any
from datetime import datetime
from pydantic import BaseModel

# A single embedding vector, kept as a plain type so nothing pgvector-specific leaks.
Embedding = list[float]


@dataclass(frozen=True, slots=True)
class DocumentDTO:
    id: UUID
    filename: str
    content_hash: str
    content: str
    owner_id: UUID
    # without this all instances without metadata would share the same empty {}
    doc_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ChunkDTO:
    id: UUID
    content: str
    document_id: UUID
    position: int
    offset_start: int
    offset_end: int


@dataclass(frozen=True, slots=True)
class OwnerDTO:
    id: UUID
    created_at: datetime
    # nullable in the DB: registered users have NULL; only anonymous mints set it.
    expires_at: datetime | None


@dataclass(frozen=True, slots=True)
class ChunkOffsets:
    content: str
    char_start: int
    char_end: int


class Citation(BaseModel):
    marker: int
    content: str
    document_id: UUID
    filename: str
    position: int


class QueryAnswer(BaseModel):
    content: str
    chunks: list[Citation]
