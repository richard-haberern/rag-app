"""Embedder plumbing: the dimension guard and the max_content_tokens budget.
No model loaded"""

import pytest

from rag_app.config import get_settings
from rag_app.embeddings.embedder import Embedder
from tests.fakes import FakeTokenizer


class _FakeST:
    """Minimal stand-in for SentenceTransformer: only the attributes Embedder.__init__ and the
    two properties touch."""

    def __init__(self, dim: int, max_seq_length: int | None) -> None:
        self._dim = dim
        self.max_seq_length = max_seq_length
        self.tokenizer = FakeTokenizer()  # num_special_tokens_to_add() -> 2

    def get_embedding_dimension(self) -> int:
        return self._dim


def _patch_st(monkeypatch, dim: int, max_seq_length: int | None = 128) -> None:
    def factory(name, device=None):
        return _FakeST(dim, max_seq_length)

    # rebinds the embedder __init__ to factory
    monkeypatch.setattr("rag_app.embeddings.embedder.SentenceTransformer", factory)


def test_embedder_rejects_dimension_mismatch(monkeypatch):
    _patch_st(monkeypatch, dim=get_settings().embed_dim + 1)
    with pytest.raises(ValueError):
        Embedder()


def test_embedder_accepts_matching_dimension(monkeypatch):
    configured = get_settings().embed_dim
    _patch_st(monkeypatch, dim=configured)
    embedder = Embedder()
    assert embedder.dimension == configured


def test_max_content_tokens_subtracts_special_tokens(monkeypatch):
    # FakeTokenizer.num_special_tokens_to_add() == 2, so the content budget is max_seq_length - 2.
    _patch_st(monkeypatch, dim=get_settings().embed_dim, max_seq_length=128)
    embedder = Embedder()
    assert embedder.max_content_tokens == 126


def test_max_content_tokens_requires_max_seq_length(monkeypatch):
    _patch_st(monkeypatch, dim=get_settings().embed_dim, max_seq_length=None)
    embedder = Embedder()
    with pytest.raises(ValueError):
        _ = embedder.max_content_tokens
