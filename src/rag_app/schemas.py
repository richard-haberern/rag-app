from dataclasses import dataclass, field
from uuid import UUID
from typing import Any
from datetime import datetime

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


@dataclass(frozen=True, slots=True)
class OwnerDTO:
    id: UUID
    created_at: datetime
    expires_at: datetime
