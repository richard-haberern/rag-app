from dataclasses import dataclass, field
from uuid import UUID
from typing import Any

# A single embedding vector, kept as a plain type so nothing pgvector-specific leaks.
Embedding = list[float]


@dataclass(frozen=True, slots=True)
class DocumentDTO:
    id: UUID
    filename: str
    content_hash: str
    content: str
    # without this all instances without metadata would share the same empty {}
    doc_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ChunkDTO:
    id: UUID
    content: str
    document_id: UUID
    position: int
