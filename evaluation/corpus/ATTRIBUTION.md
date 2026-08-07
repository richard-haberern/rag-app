# Corpus provenance

The `*.md` files in this directory are **not original work**. They are the English
documentation of [FastAPI](https://github.com/fastapi/fastapi), vendored verbatim for use as a
fixed corpus in the retrieval-evaluation harness (`evaluation/evaluation_script.py`).

| | |
|---|---|
| Source | https://github.com/fastapi/fastapi |
| Path in source | `docs/en/docs/**/*.md` |
| Path here | `fastapi-docs/` (this file and `LICENSE.fastapi` sit outside it, so `corpus/fastapi-docs/**/*.md` is the corpus glob) |
| Pinned commit | `628663f4f899c465da423bce681c7adf9a218948` |
| Retrieved | 2026-07-29 |
| Modifications | None to file contents. Non-Markdown assets (`img/`, `js/`, `css/`) were not copied, and `release-notes.md` was dropped — it is a changelog of near-identical entries and was 47% of the corpus by size. |
| License | MIT — see `LICENSE.fastapi` in this directory |
| Copyright | (c) 2018 Sebastián Ramírez |

The commit is pinned deliberately: golden spans are resolved against these exact file contents,
so re-pulling the docs at a later commit can move or delete quoted text and must be treated as a
corpus change, not a refresh.

The MIT license permits this redistribution; its sole condition is that the copyright notice and
license text accompany the copy, which `LICENSE.fastapi` satisfies. That license covers this
directory only and imposes nothing on the rest of this repository.
