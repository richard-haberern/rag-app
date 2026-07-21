# <!-- FLAG: project name --> RAG Service
 
Ask natural-language questions over your own documents. The service ingests a
document, splits it into chunks, embeds them locally, and stores the vectors. At
query time it retrieves the most relevant chunks and grounds an LLM's answer in
them — so answers are tied to your source material, not the model's training data.
 
Built backend-first, it's deployed on [Hugging Face Spaces](https://haberric-rag-app-v1.hf.space).
 
## Highlights
 
- **Multi-tenant with real auth** — username/password (argon2) plus one-click anonymous
  sessions, opaque DB-backed session tokens, and Postgres row-level security so every tenant
  sees only its own documents. All credential/session writes go through `SECURITY DEFINER`
  SQL functions, so the least-privilege app role never touches the auth tables directly.
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
- **Services** (`IngestionService`, `RetrievalService`, `QueryService`) — own the
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

- 🏠 Homepage (portfolio + contact) → <http://localhost:8080/>
- 🧪 Live demo (ingest → retrieve → answer) → <http://localhost:8080/demo.html>
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
curl -b cookies.txt -c cookies.txt -X POST http://localhost:8080/ingest/store \
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
  static/       # homepage + demo frontend (plain HTML/CSS/JS, no build step)
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

## Status & roadmap

- **v2 — complete.** Ingest → chunk → embed → store → retrieve → prompt → answer,
  end-to-end, with atomic store/delete and a passing test suite.
- **Multi-tenancy + auth — done.** Postgres RLS + least-privilege `app_user`, Alembic-managed
  schema, and a username/password + anonymous-session auth layer (argon2, DB-backed session
  tokens, `SECURITY DEFINER` SQL functions). Tenant isolation is enforced and tested.
- **Deployed** on Hugging Face Spaces against a managed Postgres with pgvector.
- **Next (v3):** a second CSRF factor (explicit `Origin` check) + rate-limiting for non-browser
  callers, a supported iframe-embed path.
- **Deferred by design:** cross-encoder reranking, document upload

---

## License

MIT