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

**pgvector only — ChromaDB dropped.**
- Vectors live in the same Postgres DB as documents and chunks, so a store or a
  delete is a **single atomic transaction** (see "Atomic writes & deletes" below).
  This is the decisive reason: a second, external vector store makes cross-store
  atomicity impossible and leaves orphan-vector / orphan-chunk windows.
- Chroma was originally kept to demonstrate a swappable seam (pgvector now → Chroma
  later). Dropped: it is a second deployed service with no free tier — dead weight —
  and the swappable seam is incompatible with the atomicity we actually want (sharing
  one pg transaction couples the store to a SQLAlchemy session anyway). One datastore,
  one deployed service.

**Local embeddings via sentence-transformers.**
- The workload doesn't need heavy compute.
- More is learned by running embeddings locally than by calling an API.

**LLM via API for generation.**

---

## Data Model & Persistence

**Atomic writes & deletes — no orphans.**
- Document, chunks and vectors all live in one Postgres DB, so a store writes them in
  a **single transaction** (`IngestionService.store_document`): they commit together
  or roll back together. No orphan-vector window.
- A delete is one `session.delete(document)` in a single transaction: the FK chain
  `stored_vectors → stored_chunks → stored_documents` (all `ON DELETE CASCADE`)
  removes chunks and their vectors in the same statement. No orphan chunks.
- This closes the orphan problem the earlier two-store design could only defer.

**`chunk_id` is code-generated, not a DB `SERIAL`.**
- The id exists before any I/O, so the vector rows can be built and inserted in the
  same transaction as their chunks without a round-trip to read generated ids.

**Two-step retrieval.**
- The vectors table holds only `(chunk_id, vector)`.
- Retrieval is `search → chunk_ids → fetch text`.

**DTOs cross the boundary, never ORM objects.**
- Returning ORM objects outside the session causes detached-object problems.
- Stores accept/return DTOs (`DocumentDTO`, `ChunkDTO`) / primitives; the extra
  ORM→DTO mapping is the accepted cost.

**Separate `chunk_store`, `doc_store`, `vector_store`.**
- Three thin, single-responsibility stores; all are stateless and take a caller-owned
  `session` (the service layer owns the transaction — see below).
- Chunk mapping keeps a `position`, which improves LLM generation when the top-k
  chunks are retrieved.
- `Chunk`: `position` (int) + `UniqueConstraint(document_id, position)`.

**Vector model PK renamed `id` → `chunk_id`.**
- Matches the `(chunk_id, vector)` shape; one vector per chunk.

**`stored_vectors` keeps an FK → `stored_chunks(chunk_id)` `ON DELETE CASCADE`.**
- Buys referential integrity + cascade deletes. This FK is the **mechanism** behind
  atomic deletes: deleting a document cascades to chunks and then to their vectors in
  one DB operation, so the service never has to purge vectors itself.

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
- Every store — including the vector store — is stateless and takes the session as an
  argument. A service opens one transaction and passes that session to `doc_store`,
  `chunk_store` and `vector_store` together, which is what makes a store or a delete
  atomic.
- Cost: a little overhead on reads and extra plumbing (services must begin/end
  sessions).

**Document dedup by content hash.**
- Two documents are duplicates if their content is identical; the hash is stored.
- Non-character documents are rejected.

**No self-heal needed — the atomic write removes the failure mode.**
- The "document + chunks stored but vectors missing" state can no longer occur: all
  three are written in one transaction, so a failure rolls the whole thing back and
  the document simply isn't stored. Dedup by content hash then lets the client retry
  cleanly.

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

## Vector Store

**No abstraction seam — one concrete `PgVectorStore`.**
- The swappable `VectorStore` Protocol was dropped along with Chroma. It only existed
  to make room for a second backend, and sharing the pg transaction for atomicity
  couples the store to a SQLAlchemy session anyway, so an "any backend" seam would be
  dishonest. `PgVectorStore` is a plain store like `DocStore`/`ChunkStore`.

**`PgVectorStore` is stateless; each method takes a `session`.**
- Reads (`search`, `get_vector_values_by_chunk_id`) and writes (`add_vectors`,
  `remove_vectors`) all run on the caller's session, so writes join the same
  transaction as the doc/chunk writes.

**Search takes a similarity threshold.**

**Search is a deterministic exact (linear) scan.**
- pgvector orders by cosine distance with `chunk_id` as a secondary key, so results
  are stable and ties break deterministically. (No HNSW/IVFFlat index at MVP scale.)

---

## Services

**Ingestion / store orchestrator.**
- On insert, the embedder blocks the whole event loop; accepted for v1.
- Deferred: move embedding off the loop with `asyncio.to_thread`.
- Embedding runs **outside** the write transaction (it's slow CPU work; don't hold a
  transaction open for it). The document, chunks and vectors are then written in one
  `begin()` block. The unit-of-work orders the inserts by FK dependency, so chunks land
  before their vectors within the single flush.
- **Document removal** is one transaction: `session.delete(document)` and let the FK
  `ON DELETE CASCADE` chain remove chunks and their vectors. No pre-read of chunk ids,
  no explicit vector purge — the DB does it atomically.
- `ChunkStore.get_chunk_ids_by_document` is now unused by the removal path (kept for its
  own test / potential reuse; it returns `[]` for a document with no chunks rather than
  raising like `get_chunks_by_document`).

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
- Duplicate content now returns **409 `DocumentExists`** (contract change — was a
  silent no-op that still returned a fresh `doc_id`). Detected by the `exists()` pre-check for
  the common case plus an `except IntegrityError` guard in `store_document` for the concurrent
  TOCTOU race. Dedup is **per-tenant**: the constraint is `UNIQUE(owner_id, content_hash)`, not a
  global unique on `content_hash` — a global one would both block a second tenant storing
  identical content and leak (via the 409) that another tenant holds it. The `IntegrityError`
  guard therefore fires only on the caller's own duplicate; narrowing to the constraint name is a
  possible later refinement.

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

**Schema bootstrap is Alembic-only; the app no longer creates schema on boot.**
- `init_db()` has been **removed from the API lifespan**. The running app connects as the
  least-privilege `app_user` (DML grants only), which cannot `CREATE EXTENSION`/`CREATE TABLE`,
  so it must never do DDL. Schema (extension + tables + RLS + policies + grants) is owned solely
  by the Alembic migration and must be applied — `alembic upgrade head`, run **as the owner
  `raguser`** — before the app can serve.
- `scripts/bootstrap-pg.sh` (run via `docker compose run --rm pg-init`) only creates the
  isolated `rag_test` database and the `app_user` role; the migration creates the `vector`
  extension. The test suite now applies the same migration against `rag_test` — see
  *Testing & CI* — so `create_all` is gone entirely; nothing bootstraps schema except Alembic.

**Docker / distribution.**
- Set the `LLM_API_KEY` env var to enable generation.
- Distribution model is "clone + build".
- DB schema is applied out-of-band via Alembic (as owner) before boot — it is **not** created
  in the API lifespan anymore. In compose, run e.g. `docker compose run --rm api alembic
  upgrade head` (the `api` service carries the owner `DATABASE_URL` for exactly this) before the
  app serves.
- Compose is three services — `pg` (pgvector), `pg-init` (one-shot, idempotent: creates
  `rag_test` + the `app_user` role, `scripts/bootstrap-pg.sh` — run explicitly with
  `docker compose run --rm pg-init`, not wired via `depends_on`, so the ordering is visible
  in a command rather than implied by compose's dependency graph), and `api`. The `api`
  service has two URLs: `APP_DATABASE_URL` (the app_user the runtime connects as, so RLS
  applies) and `DATABASE_URL` (the owner, used only to run migrations).

---

## Migrations & Multi-tenancy (RLS)

**Alembic adopted (async, pyproject config).**
- Alembic 1.18 with the pyproject layout: operational config in `[tool.alembic]`
  (`pyproject.toml`); `alembic.ini` holds only logging. `env.py` is the async template,
  injecting `sqlalchemy.url` from Settings with `Base.metadata` as target.
- Migrations/admin connect as the owner `raguser` (`DATABASE_URL`); the runtime app connects
  as `app_user` (`APP_DATABASE_URL`) — **now wired** (see *Anonymous cookie tenancy* below).

**One clean initial migration; DB reset from scratch — no destructive op in a migration.**
- The whole schema (documents/chunks/vectors + constraints, indexes, RLS, policies, grants)
  is a single initial migration — no rename/backfill/truncate churn.
- Prod holds no real data, so the transition is a **from-scratch reset** (drop tables +
  `alembic_version`, or the whole DB, then `alembic upgrade head`) done **out-of-band**,
  never as a statement inside a migration. Rationale: a `TRUNCATE` is irreversible, and
  irreversible destructive operations must not live in a migration (migrations must be
  reversible). If the DB ever holds real data before a schema change, the pattern flips to
  add-nullable → backfill → `SET NOT NULL`.

**Row-level multi-tenancy via Postgres RLS + a session GUC.**
- Shared tables with an `owner_id` discriminator on `documents` only. `chunks`/`vectors`
  isolate by **composing** through the parent's policy: their `USING`/`WITH CHECK` is a
  subselect (`document_id IN (SELECT id FROM documents)`, `chunk_id IN (SELECT id FROM
  chunks)`); the subselect is itself RLS-filtered, so a child row is visible iff its
  document is. One source of truth (a single `owner_id`), no denormalized copies to keep in
  sync. Requires an index on `chunks.document_id` (added; the FK had none).
- Policies key off `current_setting('app.owner_id', true)::uuid`. Unset → NULL →
  **fail-closed** (rows hidden, writes rejected by `WITH CHECK`). The app sets this GUC
  **transaction-locally** per request via a `set_config(..., true)` in the `set_guc_rw`/
  `set_guc_ro` dependency, which holds one `AsyncSession` (one connection, one transaction)
  open across the request — a non-local `SET` would leak tenants across pooled connections.
- **`owner_id`'s source is now the `users` registry** (resolved — see *Anonymous cookie
  tenancy*). The value is not client-supplied-and-trusted: it comes from a server-signed cookie
  (itsdangerous) validated against `users`, so a client cannot assert an arbitrary owner.

**ENABLE + FORCE — but the effective boundary is a non-owner role.**
- All three tables `ENABLE` RLS (subjects non-owner roles) and `FORCE` RLS. Caveat learned
  by testing: `FORCE` only subjects a **non-superuser** table owner. The compose/prod owner
  `raguser` is a superuser with `BYPASSRLS`, so it bypasses RLS regardless of FORCE — FORCE
  adds no protection against `raguser` as configured today. The effective isolation boundary
  is the app connecting as **`app_user`** (non-superuser, no BYPASSRLS, non-owner), verified
  fully isolated (tenant A/B cross-reads blocked, cross-writes rejected). FORCE is kept as
  harmless hygiene — it becomes meaningful only if table ownership moves to a non-superuser.

**`app_user` role is provisioning, not schema.**
- The least-privilege login role is created **outside** Alembic (a role is a cluster-global
  object and shouldn't carry a secret in migration history): `scripts/bootstrap-pg.sh`, run
  explicitly via `docker compose run --rm pg-init` (password from `APP_USER_PASSWORD`), and a
  one-time console step on prod/Neon. Idempotent and volume-age-independent (checks
  `pg_roles`/`pg_database` before creating), unlike the `docker-entrypoint-initdb.d` scripts it
  replaced, which only ever ran once, on a brand-new volume. The migration only `GRANT`s it
  `SELECT/INSERT/UPDATE/DELETE` on the three tables (+ `USAGE` on schema). No sequence grants —
  UUID PKs are client-side.
- Boundary rule: **Alembic owns intra-database schema; bootstrap-pg.sh/infra owns databases
  and roles.** Alembic can't `CREATE DATABASE` the DB it connects to, and the role must
  pre-exist the GRANT (or the migration fails fast). Never duplicate table DDL across both.
- The migration also `GRANT`s `app_user` `SELECT/INSERT/DELETE` on `users` (no `UPDATE`: a user
  row is immutable once minted). `users` is deliberately **not** under RLS — see below.

**Anonymous cookie tenancy (implemented).**
- Identity is an anonymous per-visitor `owner_id` (UUIDv4) stored in a new `users(id,
  created_at)` table — the registry the RLS `owner_id` keys off. Carried in a server-signed
  cookie (`itsdangerous.Signer`; JWT is overkill for one unguessable UUID — the signature only
  stops a client asserting a *known* other tenant's id, and retention is enforced server-side).
- **`users` has no RLS.** The cookie dependency reads it *before* `app.owner_id` is set, so an
  owner-keyed policy there would fail closed and force an infinite re-mint. It's the tenant
  registry, managed by the app, not tenant-scoped data.
- **Ownership FK drives the purge.** `documents.owner_id → users.id ON DELETE CASCADE`. Deleting
  a user cascades to its documents → chunks → vectors. The cascade is an FK action, so it bypasses
  RLS/`FORCE` even though the sweeping session has no `app.owner_id` set — but *only* as an FK
  cascade; an app-issued `DELETE FROM documents` would be ordinary RLS-filtered DML and must never
  replace it.
- **Dependency split.** `resolve_owner` validates the cookie (no mint); `require_owner` mints on
  miss (write paths only); `set_guc_rw` (writes) always sets the GUC, `set_guc_ro` (reads) sets it
  only if a valid owner exists, else leaves it unset → reads fail closed to empty. Minting is
  **write-only**: cookieless reads never create a `users` row (a crawler can't inflate the table).
- **Retention.** `TTL` (config, a `timedelta`, default 30d) is the server-side retention window;
  `cookie_expire` is the browser cookie max_age, kept aligned to TTL. Expired users are removed by
  a **probabilistic inline sweep** (~10% per mint) — accepted MVP debt (only fires with new-cookie
  traffic; the unlucky request pays the cascade delete). A background/`pg_cron` job is the later fix.

---

## Testing & CI

**Vector-store tests run once, against Postgres.**
- With Chroma gone the `vec_store` fixture is no longer parametrized over two backends;
  the interface tests exercise `PgVectorStore` directly. Because the store is stateless,
  the fixture just constructs `PgVectorStore()` and each test passes its own session.

**Postgres test database.**
- Tests run against the Compose Postgres (`test` profile) in an isolated `rag_test`
  DB; Postgres publishes host port `5432`.
- `rag_test` and the `app_user` role are provisioned idempotently by
  `docker compose run --rm pg-init` (`scripts/bootstrap-pg.sh`) — safe to re-run against
  any volume, fresh or existing, replacing the old fresh-volume-only `initdb.d` scripts.
- Schema is applied with `alembic upgrade head` against `rag_test` (`DATABASE_URL`
  pointed at it, owner creds) before the suite runs — the **same migration** as prod, so
  RLS/policies/grants are identical; `conftest.py` no longer bootstraps schema itself
  (the `setup_schema`/`create_all` fixture is gone).
- Two connections are available to tests: the plain `session` fixture (`raguser` — a
  superuser, bypasses RLS; used for everything not specifically testing isolation) and
  `app_session`/`tenant` (`app_user`, `app.owner_id` set for a fresh tenant — actually
  RLS-enforced, mirroring `api/deps.py`'s `set_guc_rw`). `APP_DATABASE_URL_TEST` (new
  `Settings` field) supplies the `app_user`→`rag_test` URL. RLS isolation is now
  testable; writing the isolation-behavior tests themselves is still open.
- Test-DB creds couple `DB_PASSWORD_TEST`/`APP_DATABASE_URL_TEST`'s password to
  `POSTGRES_PASSWORD`/`APP_USER_PASSWORD` (same roles).

**CI.**
- Uses a single `compose up` (`test` profile) to stand up Postgres, then `docker compose
  run --rm pg-init` + `alembic upgrade head` (against `rag_test`) to provision and
  schema-load it, then runs host-side pytest against it — the same sequence documented
  for local runs (README *Testing*), so CI and local no longer diverge in how the test DB
  gets ready.
- Uses a committed `.env.ci` file with test credentials against a test DB.

---

## Deferred / Out of Scope (v1)

1. ~~**`create_all` → Alembic.**~~ Resolved: the schema (prod and test) is defined solely
   by the Alembic migration (see *Migrations & Multi-tenancy*, *Testing & CI*).
   `rag_test` is schema-loaded with `alembic upgrade head`, same as prod, and
   `app_session`/`tenant` fixtures make RLS isolation testable — the remaining gap is
   writing the isolation-behavior tests themselves, not the infra to support them.
2. **Cross-encoder reranking of top-k.** v1 is bi-encoder retrieval only.
3. ~~**Orphan chunks — accepted.**~~ Resolved: store and delete are now single atomic
   transactions in one Postgres DB, so neither orphan chunks nor orphan vectors occur
   (see "Atomic writes & deletes"). No reconciler needed.
4. **Move embedding off the event loop** (`asyncio.to_thread`).
5. **Dependency pinning.** `pyproject.toml` currently uses lower-bound `>=`
   constraints, so a future package change could break us. Pin with a lockfile later.
6. **`created_at` / audit columns.**
7. **Broader out-of-scope set for v1:** auth, streaming, multiple collections, and
    document upload.
