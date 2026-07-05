import pytest
from rag_app.chunkings.factory import build_chunker
from rag_app.chunkings.chunker import Chunker


# tells pytest it is a coroutine that has to be awaited
# asyncio MODE.auto -> automatically adds this to any async def test
# the decorator is now redundant
def test_chunker_1(fake_tokenizer):
    chunker = Chunker(fake_tokenizer, 20, 5)
    text = """w01 w02 w03 w04 w05 w06 w07 w08 w09 w10 w11 w12 w13 w14 w15 w16 w17 w18 w19 w20 w21 w22 w23 w24 w25 w26 w27 w28 w29 w30 w31 w32 w33 w34 w35 w36 w37 w38 w39 w40"""
    chunks = chunker.chunk_text(text)
    assert chunks == [
        "w01 w02 w03 w04 w05 w06 w07 w08 w09 w10 w11 w12 w13 w14 w15 w16 w17 w18 w19 w20",
        "w16 w17 w18 w19 w20 w21 w22 w23 w24 w25 w26 w27 w28 w29 w30 w31 w32 w33 w34 w35",
        "w31 w32 w33 w34 w35 w36 w37 w38 w39 w40",
    ]


def test_chunker_2(fake_tokenizer):
    chunker = Chunker(fake_tokenizer, 20, 5)
    text = """w01 w02 w03 w04 w05 w06 w07 w08 w09 w10 w11 w12 w13 w14 w15 w16 w17 w18 w19 w20 w21 w22 w23 w24 w25 w26 w27 w28 w29 w30 w31 w32 w33 w34 w35 w36"""
    chunks = chunker.chunk_text(text)
    assert chunks == [
        "w01 w02 w03 w04 w05 w06 w07 w08 w09 w10 w11 w12 w13 w14 w15 w16 w17 w18 w19 w20",
        "w16 w17 w18 w19 w20 w21 w22 w23 w24 w25 w26 w27 w28 w29 w30 w31 w32 w33 w34 w35",
        "w31 w32 w33 w34 w35 w36",
    ]


def test_chunker_3(fake_tokenizer):
    chunker = Chunker(fake_tokenizer, 20, 5)
    text = """w01 w02 w03 w04 w05 w06 w07 w08 w09 w10 w11 w12 w13 w14 w15 w16 w17 w18 w19 w20 w21 w22 w23 w24 w25 w26 w27 w28 w29 w30 w31 w32 w33 w34 w35"""
    chunks = chunker.chunk_text(text)
    assert chunks == [
        "w01 w02 w03 w04 w05 w06 w07 w08 w09 w10 w11 w12 w13 w14 w15 w16 w17 w18 w19 w20",
        "w16 w17 w18 w19 w20 w21 w22 w23 w24 w25 w26 w27 w28 w29 w30 w31 w32 w33 w34 w35",
    ]


def test_chunker_empty(fake_tokenizer):
    chunker = Chunker(fake_tokenizer, 20, 5)
    text = ""
    chunks = chunker.chunk_text(text)
    assert chunks == []


def test_max_size(fake_tokenizer):
    with pytest.raises(ValueError):
        Chunker(fake_tokenizer, 0, 5)


def test_overlap(fake_tokenizer):
    with pytest.raises(ValueError):
        Chunker(fake_tokenizer, 20, -1)


def test_overlap_bigger_size(fake_tokenizer):
    with pytest.raises(ValueError):
        Chunker(fake_tokenizer, 20, 25)


def test_overlap_equal_size(fake_tokenizer):
    with pytest.raises(ValueError):
        Chunker(fake_tokenizer, 20, 20)


def test_build_chunker(fake_embedder, settings):
    settings.chunk_size = 10
    fake_embedder._max_content_tokens = 5
    with pytest.raises(ValueError):
        build_chunker(fake_embedder, settings)


def test_one_chunk_small(fake_tokenizer):
    chunker = Chunker(fake_tokenizer, 20, 5)
    text = "w01 w02 w03 w04 w05"
    chunks = chunker.chunk_text(text)
    assert chunks == ["w01 w02 w03 w04 w05"]


def test_one_chunk_full(fake_tokenizer):
    chunker = Chunker(fake_tokenizer, 20, 5)
    text = "w01 w02 w03 w04 w05 w06 w07 w08 w09 w10 w11 w12 w13 w14 w15 w16 w17 w18 w19 w20"
    chunks = chunker.chunk_text(text)
    assert chunks == [
        "w01 w02 w03 w04 w05 w06 w07 w08 w09 w10 w11 w12 w13 w14 w15 w16 w17 w18 w19 w20"
    ]


def test_non_fast_tokenizer(fake_tokenizer):
    fake_tokenizer.is_fast = False
    with pytest.raises(TypeError):
        Chunker(fake_tokenizer, 20, 5)
