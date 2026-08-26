Groundwork — RAG from scratch, down to the auth layer.
 
Ask natural-language questions over your own documents. The service ingests a
document, splits it into chunks, embeds them locally, and stores the vectors. At
query time it retrieves the most relevant chunks and grounds an LLM's answer in
them — so answers are tied to your source material, not the model's training data.
 
Built backend-first, it's deployed on [Hugging Face Spaces](https://haberric-groundwork.hf.space/).
 
## Highlights
 
- **Measured retrieval, not assumed** — a golden set of 45 quote-anchored questions over a
  154-document corpus, stratified into 7 query tiers, scored with recall / precision / MRR
  implemented over character spans. The shipped chunk size and top-k were picked from a
  20-configuration sweep, and the tier that retrieval handles *worst* is published alongside
  the one it handles best. See [Evaluation](#evaluation).
- **Multi-tenant with real auth** — username/password (argon2) plus one-click anonymous
  sessions, opaque DB-backed session tokens, and Postgres row-level security so every tenant
  sees only its own documents. All credential/session writes go through `SECURITY DEFINER`
  SQL functions, so the least-privilege app role never touches the auth tables directly.
- **Cookie-session web UI** — a dependency-free frontend (no framework, no build step)
  with three real session states (logged-out / anonymous / registered), account and
  document management, wired to the same SameSite=Lax cookie + same-origin `fetch`
  posture the API enforces (no token in JS storage).
- **Atomic ingest & delete** — documents, chunks and vectors live in one Postgres DB,
  so a store or a delete is a single transaction: it fully happens or fully rolls back,
  with no orphaned chunks or vectors.
- **Layered store/service architecture** — persistence and business logic are
  separated, and ORM objects never escape the store layer (converted to DTOs at the
  boundary), so the app depends on plain data, not live session state.
- **Deliberate test strategy** — three-tier embedder (dummy / known / real vectors),
  per-test DB isolation (including RLS-enforced tenant fixtures), and a faked LLM transport,
  so the suite is fast and runs with zero network calls.
---

## Architecture

The core design choice is a **single Postgres datastore**: documents, chunks and
vectors (via pgvector) all live in one database. That's what makes ingest and delete
**atomic** — a service opens one transaction and writes (or deletes) all three
together, so there is no window in which chunks exist without their vectors, or vice
versa.

The codebase is split into two layers:

- **Stores** (`DocStore`, `ChunkStore`, `PgVectorStore`) — own persistence only. Each
  is stateless and receives a session as an argument; it does not own or open it.
- **Services** (`IngestionService`, `RetrievalService`, `AnswerService`) — own the
  business logic and orchestrate stores.

ORM objects never escape the store layer; they're converted to DTOs at the boundary
so the rest of the app depends on plain data, not on live SQLAlchemy session state.

```mermaid
flowchart LR
    subgraph Ingest
        A[Document] --> B[Chunk]
        B --> C[Embed locally]
        C --> D[(Postgres: docs + chunks)]
        C --> E[(Postgres: pgvector)]
    end
    subgraph Query
        Q[Query] --> R[Embed locally]
        R --> S[Retrieve top-k]
        S --> T[Assemble prompt]
        T --> U[LLM API]
        U --> V[Answer]
    end
    D -. Store orchestration .-> S
    E -. vector search .-> S
```
> The diagram is the data flow only; auth/tenancy (every request resolves an owner, then RLS
> scopes the reads and writes) wraps both paths and is described below.

**Notable decisions** (full rationale in [`DECISIONS.md`](./DECISIONS.md)):

- **Embedding is a separate component from the vector store.** The store only
  persists/retrieves vectors someone else produced — it never embeds. This keeps the
  seam clean (pgvector can't embed anyway) and guarantees the *same* embedder is used
  for both ingest and query, so both live in one vector space.
- **The embedding model fixes the vector dimension** (384, baked into the pgvector
  column). One model is chosen and used for the whole app.
- **Retrieval uses a distance threshold *and* top-k** — the threshold is a quality
  gate, top-k is a ceiling.
- **Session-per-method**: stores take a session as an argument rather than owning one,
  keeping transaction boundaries in the app layer for the authorization.
- **Alembic-managed schema** — the schema (with row-level-security multi-tenancy) lives
  in Alembic migrations. The running app connects as the least-privilege `app_user` (so RLS is enforced) and no
  longer creates schema on boot; `alembic upgrade head` (run as the owner) applies it (see
  DECISIONS.md → *Migrations & Multi-tenancy*).
- **Auth is authorization + authentication, kept separate.** *Authorization* (what a tenant
  may see) is Postgres RLS keyed off a transaction-local `app.owner_id` GUC and an `owners`
  table. *Authentication* (verifying a caller) is a `session_token` cookie carrying an opaque
  bearer token — only its SHA-256 hash is stored — resolved to an owner by a DB lookup. Every
  request needs a valid session (anonymous or logged in), or it's rejected `401`. All auth
  mutations run through `SECURITY DEFINER` SQL functions the app role may only `EXECUTE`, never
  read (see DECISIONS.md → *Authentication & Sessions*).

---

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| API | FastAPI (async) | RAG is I/O-bound JSON endpoints, not server-rendered pages |
| DB | PostgreSQL + pgvector | text and vectors stay consistent in one datastore |
| ORM | SQLAlchemy async + asyncpg | models the document↔chunk relation cleanly |
| Embeddings | sentence-transformers (`all-MiniLM-L6-v2`, 384-dim) | small, free, runs locally — unlimited dev loop |
| Generation | Gemini 2.5 Flash via `httpx` | generation models are too large to host; API call instead, no vendor SDK |
| Auth | argon2 (`argon2-cffi`) + opaque session tokens + Postgres RLS | password hashing off the event loop; RLS enforces tenant isolation in the DB |
| Tests | pytest + pytest-asyncio | — |

---

## Quickstart

**Prerequisites:** Docker + Docker Compose.

```bash
# 1. Create a .env (compose auto-loads it)
cat > .env <<'EOF'
POSTGRES_PASSWORD=change-me
APP_USER_PASSWORD=change-me-too   # least-privilege RLS role, provisioned by pg-init
LLM_API_KEY=your-gemini-api-key   # required — generation calls Gemini
SWEEP_TOKEN=some-long-secret      # optional — gates POST /admin/cleanup (retention sweep)
# SECURE=true                     # set when serving over HTTPS, so the session cookie is Secure
EOF

# 2. Build images, start Postgres, provision it (rag_test db + app_user role), and
#    apply the schema as the OWNER (raguser). The app runs as the least-privilege
#    app_user and does NOT create schema on boot, so the migration must run first.
docker compose build
docker compose up -d pg
docker compose run --rm pg-init
docker compose run --rm api alembic upgrade head

# 3. Start the app
docker compose up api
```

> ⏳ **First build/run is slow.** The api image installs **PyTorch** (~a few GB), and
> on first startup the embedding model is downloaded. Expect several minutes the first
> time — later runs are fast.

Once it's up (Compose publishes the app on host port **8080** → `8080:8000`):

- 🏠 Homepage (overview + contact) → <http://localhost:8080/>
- 🖥️ Web app — register or continue anonymously, ingest documents, ask questions, and
  manage your account & documents → <http://localhost:8080/demo.html>
- 📖 Interactive docs (Swagger) → <http://localhost:8080/docs>

The database schema is applied by the Alembic migrations in step 2 (the pgvector extension;
the `owners`, `users`, `sessions`, `documents`, `chunks` and `vectors` tables, with RLS; and
the `SECURITY DEFINER` auth functions). The app itself connects as `app_user` and does not
create schema.

> **Migrations & multi-tenancy.** The RLS-enabled schema is defined by an Alembic
> migration (`alembic upgrade head`); `docker compose run --rm pg-init` provisions the
> `app_user` role (`scripts/bootstrap-pg.sh`, idempotent — safe to re-run against any
> volume, fresh or existing). To reset from scratch (safe — no real data): local
> `docker compose down -v` then re-run `pg-init` + the migration; on prod/Neon create
> `app_user` once via the console, then `alembic upgrade head`. Never truncate/backfill
> inside a migration.

### Run locally (without Docker)

```bash
uv sync                                   # creates .venv from uv.lock; needs Python 3.12
# Postgres with pgvector running. In .env set:
#   DATABASE_URL      -> owner (raguser) connection, used by Alembic
#   APP_DATABASE_URL  -> app_user connection, used by the running app (RLS applies)
#   LLM_API_KEY       -> generation
#   SWEEP_TOKEN       -> optional, gates POST /admin/cleanup
uv run alembic upgrade head               # apply schema as the owner (DATABASE_URL), once
uv run uvicorn rag_app.api.main:app --reload  # serves on http://localhost:8000
```

### Example

A full auth → ingest → ask → fetch round-trip. Every request needs a valid session, so start
by minting one — the simplest is a one-click anonymous session (or `POST /register` then
`POST /login` for a username/password account). The session rides a `session_token` cookie, and
you only ever see your own documents, so carry the cookie across every call (`-c`/`-b` a jar):

```bash
# 0. Mint an anonymous session — sets the session_token cookie (saved to cookies.txt)
curl -c cookies.txt -X POST http://localhost:8080/anonymous_login
# → "Anonymous login successful. Welcome!"

# 1. Ingest a document — returns the doc id
curl -b cookies.txt -c cookies.txt -X POST http://localhost:8080/store \
  -H "Content-Type: application/json" \
  -d '{
        "filename": "pangram.txt",
        "content": "The quick brown fox jumps over the lazy dog.",
        "metadata": {"source": "demo"}
      }'
# → "3fa85f64-5717-4562-b3fc-2c963f66afa6"

# 2. See what retrieval finds — the top-k chunks for a query, in similarity order
curl -b cookies.txt -X POST http://localhost:8080/query/retrieve \
  -H "Content-Type: application/json" \
  -d '{"query": "What does the fox jump over?"}'
# → ["The quick brown fox jumps over the lazy dog."]

# 3. Ask a question — the answer is grounded in your ingested documents
curl -b cookies.txt -X POST http://localhost:8080/query/generate \
  -H "Content-Type: application/json" \
  -d '{"query": "What does the fox jump over?"}'
# → "The fox jumps over the lazy dog."

# 4. (optional) Fetch a stored document by id
curl -b cookies.txt http://localhost:8080/query/documents/3fa85f64-5717-4562-b3fc-2c963f66afa6
```

---

## Project layout

```
src/rag_app/
  api/          # FastAPI app, routes (ingest, query, auth, dev), deps, cookie/session helpers
  services/     # IngestionService, RetrievalService, AnswerService
  stores/       # DocStore, ChunkStore, PgVectorStore (persistence only)
  models/       # SQLAlchemy ORM models (owner, user, session, document, chunk, vector)
  exceptions/   # AppError hierarchy (each carries its own HTTP status)
  chunkings/    # chunker + factory
  embeddings/   # sentence-transformers wrapper
  llm/          # LLM client + factory + prompter
  db/           # engine, base
  eval/         # retrieval metrics: Span, recall, precision, MRR (library code, corpus-agnostic)
  static/       # homepage + web app UI: auth, account & document management, ingest/ask (plain HTML/CSS/JS, no build step)
evaluation/     # golden set + sweep harness: goldens.jsonl, evaluation_script.py, corpus/
alembic/        # migrations: initial RLS schema, HNSW index, auth schema + SQL functions
functions.sql   # reference copy of the SECURITY DEFINER auth functions (installed by the migration)
tests/
```

---

## Testing

Tests run against the Compose Postgres (`test` profile) in an isolated `rag_test`
database, published on `localhost:5432`. Bring it up and apply the schema once (both
steps are idempotent — safe to re-run):

```bash
docker compose --profile test up -d --wait pg
docker compose run --rm pg-init                                        # rag_test db + app_user role
DATABASE_URL=postgresql+asyncpg://raguser:$POSTGRES_PASSWORD@localhost:5432/rag_test \
  uv run alembic upgrade head                                          # schema, incl. RLS/policies/grants
uv run pytest
```

The test design is deliberate:

- **Isolation** via truncate-before-yield fixtures, so each test starts from a clean DB.
- **Schema parity with prod**: `rag_test` is provisioned by the same Alembic migration as
  the real DB (not a separate `create_all` path), so RLS/policies/grants are identical.
- **RLS is testable**: `app_session`/`tenant` fixtures (`tests/conftest.py`) open a
  connection as `app_user` with `app.owner_id` set for a fresh tenant, so tenant-isolation
  behavior can be asserted directly, alongside the plain `session` fixture (`raguser`,
  bypasses RLS — a superuser) used for everything else.
- **Three-tier embedder strategy**: dummy vectors for store/ingest tests, hand-placed
  known vectors for retrieval-SQL tests (so distances are predictable), and the real
  model only for end-to-end tests.
- **The LLM client is faked** with `httpx.MockTransport` — no network calls in tests.

CI (`.github/workflows/ci.yaml`) runs the same sequence against a committed `.env.ci`.

---

## Evaluation

Retrieval quality is **measured, not asserted**. The tests above prove the pipeline is
*correct*; this proves it *works* — and bounds how well. Full rationale for every choice
below lives in [`DECISIONS.md`](./DECISIONS.md) → *Retrieval-evaluation golden set*.

Retrieval recall is a **ceiling on end-to-end quality**: what retrieval misses, generation
cannot recover.

### The golden set

`evaluation/goldens.jsonl` — **45 questions, 76 gold spans**, over the FastAPI English docs
(`evaluation/corpus/fastapi-docs/`, 154 files, MIT, vendored verbatim at pinned commit
`628663f`). `release-notes.md` was dropped: a changelog of near-identical entries, 47% of the
corpus by size, that would have dominated embedding cost and contributed only near-duplicates.

Two decisions do the load-bearing work:

- **Goldens are quote-anchored, not offset-anchored.** Each answer names a document and a
  *verbatim quote*, resolved to character offsets at load time. Integer offsets would rot
  silently the moment the corpus changed — and every metric downstream would be wrong with no
  error. Quotes must come from the raw Markdown, never the rendered docs site, which strips
  `**bold**`, backticks and `<abbr>` tags.
- **The loader fails loud.** `occurrence` is the expected *total* match count, not an index, and
  a disagreement raises rather than taking the first hit. Matches must also land on **word
  boundaries** — a truncated quote is still a legal substring, so it resolves silently and shifts
  every offset after it. That is the one failure mode counting alone does not catch.

### Query tiers

Each golden carries a tier isolating a distinct failure mode. Tiers are **reported separately,
never averaged into one number** — they move in *opposite directions* under chunk size, so a
single mean cancels the effect the sweep exists to measure.

| tier | n | what it isolates | recall@8 |
|---|---|---|---|
| `needle` | 4 | one fact stated in exactly one place | 1.00 |
| `paraphrase` | 10 | the question reworded | 0.75 |
| `multi-hop` | 6 | needs ≥2 spans, 4 of 6 cross-document | 0.75 |
| `lexical` | 8 | phrased near-identically to the source — a regression floor | 0.58 |
| `vocabulary-shift` | 7 | the key term is **absent from the query** | 0.43 |
| `distractor` | 6 | a term whose wrong sense has more surface area than the right one | 0.42 |
| `unanswerable` | 4 | no gold spans — **excluded from retrieval metrics** | — |

Scored at the shipped config (192-token chunks, k=8) over the 41 scored goldens.

- `vocabulary-shift` is the only tier that sees embedding quality separately from lexical
  overlap, since paraphrase goldens still share content words with their spans. Enforced when
  authoring: a query whose content words overlap its own gold spans is not a vocabulary shift.
- `multi-hop` is the **only tier where recall < 1.0 is the expected result** — `recall()` divides
  by the number of gold spans, so retrieving one hop of two scores exactly 0.5. That is the
  measurement, not a regression.
- `unanswerable` goldens are stored but carry no retrieval signal: `recall()` would divide by
  zero and precision/MRR return a constant `0.0`. They become useful at the *answer* layer
  ("does the model decline instead of inventing"), which is a different measurement.

### Metrics

`src/rag_app/eval/metrics.py` — recall, precision and MRR computed over **character spans**, not
chunk ids, so they survive re-chunking. A chunk counts as relevant when it covers ≥ τ = 0.5 of a
gold span. **Mean characters retrieved** is reported next to every recall number: recall bought
by raising k is paid for in context, and quoting one without the other is dishonest.

### The sweep

`evaluation/evaluation_script.py` ingests the corpus at 4 chunk sizes and scores every golden at
5 values of k. Aggregate recall, micro-averaged over the 41 scored goldens:

| chunk | k=2 | k=4 | k=6 | k=8 | k=10 |
|---|---|---|---|---|---|
| 64 | 0.385 | 0.446 | 0.528 | 0.535 | 0.581 |
| 128 | 0.297 | 0.384 | 0.499 | 0.571 | 0.615 |
| **192** | 0.397 | 0.508 | 0.578 | **0.638** | 0.662 |
| 254 | 0.403 | 0.482 | 0.627 | 0.746 | 0.746 |

**Chunk size and k interact as a threshold, not a trade-off.** At 64 and 128 tokens the gold span
is fragmented so no chunk clears τ, and `needle` recall is *completely inert to k* — 0.46 and 0.50
respectively, unchanged from k=2 all the way to k=10. More retrieved context cannot fix a chunking
failure. Above that floor k starts paying: 192-token chunks reach 1.00 on `needle` by k=8.

### Why 192 / k=8 ships

Set via `CHUNK_SIZE=192` and `RETRIEVAL_TOP_K=8`. **254/k=8 has the higher aggregate recall**
(0.746 vs 0.638) and was rejected anyway:

| | vocabulary-shift | multi-hop | chars retrieved |
|---|---|---|---|
| 192 / k=8 | **0.43** | **0.75** | **5,204** |
| 254 / k=8 | 0.36 | 0.67 | 6,666 |

192 wins the two tiers that most resemble how questions actually get asked, on **22% less
context**. The aggregate is carried by `lexical` and `distractor` — the least representative
tiers — so optimising the headline number would have optimised the wrong thing.

### What these numbers do not say

- **n = 41.** The unpaired standard error is ≈ 0.07, so the 0.746 vs 0.638 aggregate gap is
  *inside the noise*. The config choice rests on the per-tier pattern, not the headline. A paired
  test over the per-query rows would settle it and has not been run.
- **`retrieval_threshold` was never swept** — held at 0.7 throughout, the one dimension the sweep
  does not cover. It was checked for confounding: 92–110% of expected chunks return at k=10 across
  every tier, so the gate is not truncating before k and the 0.43 `vocabulary-shift` ceiling is a
  ranking limit, not a threshold artifact.
- **This measures retrieval, not answers.** Precision sits at ≈ 0.14, so most of what reaches the
  prompt is irrelevant; whether that pollution degrades generation is a separate measurement.
- **MRR is flat (≈ 0.47–0.49) while recall climbs 0.30 → 0.75 across k.** The right chunks are
  being retrieved but ranked deep — which is exactly the signal that cross-encoder reranking would
  pay off, and why it is the next lever rather than a nice-to-have.

### Running it

```bash
# Same Postgres as the test suite (see Testing above), plus the real embedding model.
uv run python -m evaluation.evaluation_script
```

Goldens are resolved *before* the corpus is ingested, so a bad quote fails in a second rather
than after embedding 154 documents at four chunk sizes.

---

## Status & roadmap

- **v2 — complete.** Ingest → chunk → embed → store → retrieve → prompt → answer,
  end-to-end, with atomic store/delete and a passing test suite.
- **Multi-tenancy + auth — done.** Postgres RLS + least-privilege `app_user`, Alembic-managed
  schema, and a username/password + anonymous-session auth layer (argon2, DB-backed session
  tokens, `SECURITY DEFINER` SQL functions). Tenant isolation is enforced and tested.
- **Deployed** on Hugging Face Spaces against a managed Postgres with pgvector.
- **Next (v3):** a second CSRF factor (explicit `Origin` check) + rate-limiting for non-browser
  callers, a supported iframe-embed path.
- **Deferred by design:** cross-encoder reranking (deferred with evidence — see
  [Evaluation](#evaluation): flat MRR against climbing recall is the signal it would pay off),
  document upload

---

## License

MIT