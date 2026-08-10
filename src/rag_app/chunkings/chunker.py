from typing import TYPE_CHECKING
from rag_app.schemas import ChunkOffsets

if TYPE_CHECKING:
    # Type-only import: transformers is already pulled in transitively by sentence-transformers,
    # so we don't make it a hard runtime dependency just for a hint.
    from transformers import PreTrainedTokenizerBase


class Chunker:
    def __init__(
        self, tokenizer: "PreTrainedTokenizerBase", max_size: int, overlap: int
    ) -> None:
        # return_offsets_mapping is only available on fast (Rust-backed) tokenizers; a slow one
        # would fail deep inside chunk_text, so reject it up front. The model-window ceiling on
        # max_size is enforced in build_chunker (where the model is known), not here.
        if not tokenizer.is_fast:
            raise TypeError(
                "Chunker needs a fast tokenizer; return_offsets_mapping requires tokenizer.is_fast"
            )
        if max_size <= 0:
            raise ValueError("max_size must be > 0")
        if not 0 <= overlap < max_size:
            raise ValueError("overlap must satisfy 0 <= overlap < max_size")
        self.tokenizer = tokenizer
        self.max_size = max_size
        self.overlap = overlap

    def chunk_text(self, text: str) -> list[ChunkOffsets]:
        # verbose=False: we deliberately tokenize the whole document, which is far longer than
        # the model window, because all we want is offset_mapping - these ids never reach the
        # model, only the sliced <=max_size chunks do. Without it transformers logs a bogus
        # "sequence length is longer than the specified maximum" warning about a truncation
        # that isn't happening here (sentence-transformers lowers model_max_length to 256).
        out = self.tokenizer(
            text, return_offsets_mapping=True, add_special_tokens=False, verbose=False
        )
        offsets = out["offset_mapping"]
        # guarded also at ingestor with checking for empty doc, but chunker itself has to be safe
        if not offsets:
            return []
        char_start = char_end = 0
        tok_start = tok_end = 0
        ret: list[ChunkOffsets] = []
        while True:
            if tok_start + self.max_size >= len(offsets):
                char_start = offsets[tok_start][0]
                ret.append(ChunkOffsets(text[char_start:], char_start, len(text)))
                return ret

            tok_end = tok_start + self.max_size
            char_start = offsets[tok_start][0]
            char_end = offsets[tok_end - 1][1]
            ret.append(ChunkOffsets(text[char_start:char_end], char_start, char_end))
            tok_start = tok_end - self.overlap
