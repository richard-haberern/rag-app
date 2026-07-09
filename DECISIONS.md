# Architecture Decisions

Living record of the architectural choices for this RAG app and *why* they were
made. Scope is the **v1 MVP**: correct end-to-end, backend-first. Anything marked
deferred is intentionally out of scope for v1 — see the final section.

---

## Stack

**FastAPI (async).**
- Native async; a clear fit for an I/O-bound JSON API and AI-oriented apps.
- Prior experience from the MINI-RAG project.

**Not Django.**
- Oriented toward server-rendered page apps; its "batteries" don't apply to a
  pure JSON API.

**PostgreSQL + SQLAlchemy (async) + asyncpg.**

**pgvector first, ChromaDB migration.**
- pgvector keeps the first MVP simple (vectors live in the same DB as chunks).
- Building the infrastructure so it migrates cleanly to ChromaDB is a valuable
  skill in its own right.

**Local embeddings via sentence-transformers.**
- The workload doesn't need heavy compute.
- More is learned by running embeddings locally than by calling an API.

**LLM via API for generation.**

---

## Data Model & Persistence

**No cross-store atomicity; orphan chunks accepted, orphan vectors not.**
- Atomicity across Postgres and the vector store is impossible with the migration to Chroma
- Write order is **chunks first, then vectors**. This can leave orphan chunks
  (chunk with no vector); that is a documented, accepted problem for v1 and will
  be resolved later. Orphan *vectors* are prevented by the store orchestration.

**`chunk_id` is code-generated, not a DB `SERIAL`.**
- The id exists before any I/O, so it does not force the write ordering
  (chunk-then-vector).

**Two-step retrieval.**
- The vector store holds only `(chunk_id, vector)` — Chroma-shaped.
- Retrieval is `search → chunk_ids → fetch text`.

**DTOs cross the boundary, never ORM objects.**
- Returning ORM objects outside the session causes detached-object problems.
- Stores accept/return DTOs (`DocumentDTO`, `ChunkDTO`) / primitives; the extra
  ORM→DTO mapping is the accepted cost.

**Separate `chunk_store`, `doc_store`, `vector_store` (vector store swappable).**
- Chunk mapping keeps a `position`, which improves LLM generation when the top-k
  chunks are retrieved.
- `Chunk`: `position` (int) + `UniqueConstraint(document_id, position)`.

**Vector model PK renamed `id` → `chunk_id`.**
- Matches the `(chunk_id, vector)` shape; one vector per chunk.

**`stored_vectors` keeps an FK → `stored_chunks(chunk_id)` `ON DELETE CASCADE`.**
- Buys referential integrity + cascade deletes (not the `search()` return shape).
- NOTE: this FK is **pgvector-only** — it couples the store to Postgres and will
  **not** carry over to a ChromaDB store.

**`doc_metadata` is a JSONB column, dict `str → Any`; keys must be `str`.**
- ORM attribute is `doc_metadata` because `metadata` is reserved by SQLAlchemy's
  declarative registry.

**pgvector column dimension comes from one config value `EMBED_DIM=384`.**
- Single source of truth for the vector dimension.

**One shared async engine + `async_sessionmaker(expire_on_commit=False)`.**
- DB credentials from `.env` (`DATABASE_URL`).

**DB SSL is a per-env `DB_SSL` setting (default `false`).**
- `make_engine` passes `connect_args={"ssl": DB_SSL}` to asyncpg. Managed Postgres
  (Neon) requires SSL; the local + CI/test Postgres doesn't speak TLS and rejects an
  SSL upgrade. One engine factory serves both, so the flag can't be hardcoded.
- Deploy env sets `DB_SSL=true`; local/CI/tests inherit the `false` default.
- Rejected auto-detecting SSL from the host (localhost → off) as too implicit — an
  explicit per-env toggle is clearer.
- Note: asyncpg wants `connect_args["ssl"]` (bool/SSLContext), **not** libpq's
  `sslmode` URL query param.

**Services own the session makers and the transaction boundaries.**
- Sessions are passed into the store methods: we gain write atomicity while
  keeping the vector store seam swappable.
- Cost: a little overhead on reads and extra plumbing (services must begin/end
  sessions).

**Document dedup by content hash.**
- Two documents are duplicates if their content is identical; the hash is stored.
- Non-character documents are rejected.

**No self-heal — dedup is preferred over self-heal.**
- If a document + chunks are stored but the vectors are not, we cannot re-store to
  fill the vectors, because dedup rejects the second attempt.

**Ingest takes content from the request body (path → content redesign).**
- Documents are sent as `content` in the request body; the service no longer reads
  the filesystem. A path, if present, is just optional metadata.
- Original content is stored verbatim on the `Document` row (a `content` column),
  not reconstructed from chunks: joining chunks duplicates the overlap region and
  drops boundary whitespace, so it isn't faithful. We accept storing content twice
  (row + chunks) for an exact, simple read.

---

## Embedding

**Model: `all-MiniLM-L6-v2` (dim 384).**
- Best fit for the v1 MVP: local, easy, fast on CPU with no GPU.
- Relatively small and an industry standard; not the strongest embedder, but
  enough for the MVP and easy to swap later based on MTEB.

**Cosine distance for similarity search.**
- `all-MiniLM-L6-v2` is optimized for cosine similarity.

**Two methods on the embedding class: `embed_document` and `embed_query`.**
- Many transformers use a different routine for each, so exposing both keeps the
  interface ready for a future model swap.

---

## Vector Store Seam

**All vector access goes through a single swappable interface.**

**Seam is currently a Protocol, not an ABC inheritance hierarchy.**

**The current seam is concrete, compatible-shaped classes — a formal, abstract
`VectorStore` / `Embedder` Protocol is deferred.**
- The `chunk_vectors → chunks` FK is pgvector-only and won't port to Chroma.

**Chroma is a first-class dependency.**
- Without a connection to ChromaDB the app won't start.

**Search takes a similarity threshold.**

**Chroma vector store searches ANN and doesn't have a secondary ordering rule which can lead to different found vectors than Postgres (pgvector) that does linear seach and has a deterministic search with ChunkID**

---

## Services

**Ingestion / store orchestrator.**
- On insert, the embedder blocks the whole event loop; accepted for v1.
- Deferred: move embedding off the loop with `asyncio.to_thread`.
- **Document removal** goes through `VectorStore.remove_vectors` explicitly rather than
  relying on the pg cascade: deleting a `Document` cascades to chunks and the pg
  `stored_vectors` table, but that cascade never reaches an external store (Chroma), so
  the service must purge it via the interface.
- Ordering mirrors `store_document`: delete the pg document first (authoritative), then
  purge the external vectors. A Chroma-purge failure therefore leaves orphan vectors
  whose chunk ids no longer resolve — symmetric with the store path's "vectors added
  after commit" window. See Deferred #3 (orphan chunks/vectors accepted, no reconciler).
- Chunk ids are read *before* the delete (the cascade removes chunks) via the new
  `ChunkStore.get_chunk_ids_by_document`, which returns `[]` for a document with no
  chunks instead of raising like `get_chunks_by_document` (empty is a valid delete state).

**Retrieval.**
- Deferred: cross-encoder re-ranking of the top-k.

**Prompt builder.**
- No citations in v1.

**LLM client.**
- v1 uses Gemini's free-tier Flash 2.5: fast answers, free for development. Note
  the free tier trains on submitted queries — acceptable for v1.
- The client is swappable.
- Prompts go out over `httpx` directly — no extra dependency on an
  `anthropic` / `openai` / … SDK.
- Uses a shared `AsyncClient` for connection pooling, since we make the same HTTPS
  call repeatedly. The `AsyncClient` is **injected** (cheaper, more testable, in
  line with the project architecture) and is owned by the caller, not the
  `LLMClient`.

---

## API & Infrastructure

**FastAPI HTTP layer.**
- Documents are accepted as `str` content inside JSON — no document parsing.
- Uses routes for a clean architecture.
- Deferred: document upload.
- API runs on port **8080**.

**Exception architecture.**
- One root, `AppError` (`rag_app/exceptions`), for every error the app raises on purpose.
  Each class carries a `status_code`, so a **single** `@app.exception_handler(AppError)`
  turns any subclass into a response (Starlette dispatches to the most specific registered
  class by MRO). Per-type handlers are therefore unnecessary and were removed.
- The tree splits by responsibility, not just by name:
  - `RagError` (4xx, client): `DocumentNotFound` (404), `EmptyDocument` (422),
    `QueryError` (413).
  - `InternalError` (5xx, invariant violations): `ChunkNotFound`, `VectorNotFound` — these
    mean the data is inconsistent (a chunk with no vector, a document with no chunks), not
    that the client asked for something missing, so they are **not** 404s. Both are
    internal-only today (no routed caller); kept for defense-in-depth.
  - `LLMError` (502, upstream): wraps **all** httpx failures (status, timeout, connection)
    raised in `LLMClient.generate`, plus `LLMBadAnswer` for a malformed 200 body. Reports
    the upstream status code only — `str(exc)` would leak the Gemini URL.
- A last-resort `@app.exception_handler(Exception)` returns a generic 500 envelope so
  nothing unforeseen leaks internals.
- Removed the old `OSError → 404` handler (the request path no longer touches the
  filesystem; a stray socket error mapping to 404 was misleading) and the blanket
  `ValueError → 500` (genuinely-internal `ValueError`s fall through to the catch-all).
- The exceptions module holds plain int status codes and does **not** import FastAPI —
  the domain layer stays decoupled from the web framework.
- Duplicate `content_hash` now returns **409 `DocumentExists`** (contract change — was a
  silent no-op that still returned a fresh `doc_id`). Detected by the `exists()` pre-check for
  the common case plus an `except IntegrityError` guard in `store_document` for the concurrent
  TOCTOU race. Assumes `content_hash` is the only unique constraint a fresh-`uuid4` insert can
  violate in that transaction; narrowing to the constraint name is a possible later refinement.

**Additive `POST /query/retrieve` endpoint for the demo frontend.**
- The demo must *show* retrieval (the chunks are the proof the pipeline works), but
  `/query/generate` returns only the answer string. Rather than change its response
  shape (an API contract break), retrieval is exposed as a separate additive endpoint.
- Response is `list[str]` (chunk contents in similarity order) because that is what
  `RetrievalService.search_topk_chunks` returns — scores never cross the service
  boundary, so the endpoint can't expose them without a core-signature change (deferred).
- Uses the same `RETRIEVAL_TOP_K` / `RETRIEVAL_THRESHOLD` defaults as generation. The
  demo calls retrieve + generate concurrently, so retrieval work runs twice per demo
  query; accepted for v1.

**Static frontend served by FastAPI from package data.**
- Homepage (`/`) + demo (`/demo.html`) are plain HTML/CSS/vanilla JS in
  `src/rag_app/static/` — no build step, no node, no CDN libs, zero new Python deps
  (`StaticFiles` ships with Starlette).
- Mounted at `/` with `html=True`, registered *after* all routers, so `/docs`,
  `/openapi.json` and the API routes always win — the mount only catches leftovers.
- Assets live **inside the package** and are declared as setuptools `package-data`
  because the Docker image ships only the installed venv (no repo tree); a repo-root
  `static/` dir would exist locally but not in the container.
- The frontend uses relative fetch URLs (same origin), so no CORS middleware is needed.

**Schema bootstrap is split by vector backend.**
- `init_db()` creates only the always-present relational schema: the documents and chunks
  tables. These live in Postgres regardless of the chosen vector store.
- `init_pgvector()` creates the pgvector extension + the `stored_vectors` table, and runs
  **only** when `VECTOR_DB=Postgres`. In Chroma mode neither the extension nor the vectors
  table is ever created.
- `init.sql` (the container's fresh-volume init) no longer creates the extension — it only
  creates the isolated `rag_test` database. Consumers that need the extension create it
  themselves: the app via `init_pgvector` (Postgres mode), the test suite via its
  `setup_schema` fixture.
- `create_all` only creates missing tables; it never `ALTER`s an existing one, so
  a model change silently leaves the live table on the old schema.
- Dev workaround: drop and recreate.
- `CREATE EXTENSION` needs a privileged role — fine in the local container, but a
  deployment-time concern once it leaves the container.
- Alembic deferred.

**Docker / distribution.**
- Set the `LLM_API_KEY` env var to enable generation.
- Distribution model is "clone + build".
- The DB bootstrap lives in the API lifespan for v1; with Alembic it will move out.
- **Vector backend selection in the container.** `.env` is `.dockerignore`'d, so the app never
  reads it inside the image; the choice is passed explicitly via compose
  (`api.environment: VECTOR_DB: ${VECTOR_DB:-ChromaDB}`), substituted from the host env / project
  `.env` at `up` time. Consequence: changing the backend needs a container recreate (not a code
  rebuild), and a stale image will still run its own baked bootstrap — rebuild (`--build`) after
  bootstrap changes.

---

## Testing & CI

**Chroma test suite.**
- Each test gets an independent collection, torn down after use.
- Runs against an actual Docker DB — Chroma's in-memory client is synchronous only,
  which is unusable for this project.
- Port split: the API's fixed mapping is `8080:8000`, so the test-suite Chroma can
  keep the default port `8000` unchanged.
- The Chroma image has no `curl`/`wget`/`python`, so a Docker Compose healthcheck
  isn't possible; the healthcheck is done app-side, in both the app and the tests.
- `AsyncHttpClient.make_client()` performs the DB connection check eagerly (tested),
  not lazily — that's why we retry client *creation*, not just the connect.

**Postgres test database.**
- Tests run against the Compose Postgres (`test` profile) in an isolated `rag_test`
  DB as `raguser`; Postgres now publishes host port `5432`.
- Test-DB creds couple `DB_PASSWORD_TEST` to `POSTGRES_PASSWORD` (same role).

**CI.**
- Uses a single `compose up` file instead of GitHub services, because Chroma has to
  be in a compose file and we keep everything unified — both go through the compose
  file.
- Uses a committed `.env.ci` file with test credentials against a test DB.

---

## Deferred / Out of Scope (v1)

1. **`create_all` → Alembic.** `create_all` only creates missing tables; it never
   `ALTER`s an existing one, so a model change silently leaves the live table on the
   old schema. Dev workaround is drop + recreate.
2. **Cross-encoder reranking of top-k.** v1 is bi-encoder retrieval only.
3. **Orphan chunks — accepted.** No reconciliation / cleanup job. Orphan vectors are
   prevented in the store orchestration.
4. **Move embedding off the event loop** (`asyncio.to_thread`).
5. **Dependency pinning.** `pyproject.toml` currently uses lower-bound `>=`
   constraints, so a future package change could break us. Pin with a lockfile later.
6. **`created_at` / audit columns.**
7. **Broader out-of-scope set for v1:** auth, streaming, multiple collections, and
    document upload.
