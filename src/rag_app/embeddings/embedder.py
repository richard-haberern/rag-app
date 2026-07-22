from typing import Any

from sentence_transformers import SentenceTransformer
from numpy import ndarray
from threading import Lock

from rag_app.config import get_settings
from rag_app.schemas import Embedding


class Embedder:
    def __init__(self) -> None:
        settings = get_settings()
        self.model = SentenceTransformer(
            settings.embed_model_name, device=settings.embed_device
        )
        self._batch_size = settings.embed_batch_size
        self._lock = Lock()
        # Guard: the model's dimension must match the configured (and pgvector-baked) one.
        actual = self.model.get_embedding_dimension()
        if actual != settings.embed_dim:
            raise ValueError(
                f"Embedding model dim {actual} != configured EMBED_DIM "
                f"{settings.embed_dim}; the pgvector column dimension would mismatch."
            )

    @property
    def dimension(self) -> int | None:
        return self.model.get_embedding_dimension()

    # The chunker tokenizes with the *same* tokenizer used here, so ingest/query stay in one
    # token space. Expose it (and the usable token budget) instead of letting callers reach
    # into self.model — keeps the SentenceTransformer behind this seam.
    @property
    def tokenizer(self) -> Any:
        return self.model.tokenizer

    @property
    def max_content_tokens(self) -> int:
        # max_seq_length is the model's hard ceiling; the embedder will add special tokens
        # ([CLS]/[SEP]) at encode time, so the room left for real content is that minus the
        # special-token budget. num_special_tokens_to_add() keeps this model-agnostic.
        max_seq = self.model.max_seq_length
        if max_seq is None:
            raise ValueError(
                f"Model {self.model} has no max_seq_length; cannot derive a chunk size."
            )
        return max_seq - self.model.tokenizer.num_special_tokens_to_add()

    # use the lock (both embed methods) so prevent that ST doesn't guarantee
    # that a single model is safe for concurrent calls - we run these from
    # a different thread so we don't block the event loop
    def embed_document(self, texts: list[str]) -> list[Embedding]:
        with self._lock:
            emb = self.model.encode_document(
                texts, batch_size=self._batch_size, convert_to_numpy=True
            )
        assert isinstance(emb, ndarray)
        return emb.tolist()

    def embed_query(self, query: str) -> list[Embedding]:
        # Single-element outer list, per the agreed return shape.
        with self._lock:
            emb = self.model.encode_query(
                [query], batch_size=self._batch_size, convert_to_numpy=True
            )
        assert isinstance(emb, ndarray)
        return emb.tolist()
