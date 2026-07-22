# Architecture Decisions

Living record of the architectural choices for this RAG app and *why* they were
made. Scope is the **v2**: correct end-to-end, backend-first. Anything marked
deferred is intentionally out of scope for v2 — see the final section.

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
  `session` (the app owns the transactions — see below).
- Chunk mapping keeps a `position`, which improves LLM generation when the top-k
  chunks are retrieved.

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

**The app owns the session makers and the transaction boundaries.**
- Every store and service — is stateless and takes the session as an
  argument. The app opens one transaction with the GUC set for correct authorization and passes that session to all of the *services* which then pass it to all of the *stores*, what makes all of the deletes and inserts **atomic**.
- Cost: a little overhead on reads 

**Document dedup by content hash.**
- Two documents are duplicates if their content is identical; the hash is stored.
- Non-character documents are rejected.


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
- Best fit for the v2: local, easy, fast on CPU with no GPU.
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

**Search uses HNSW ANN index.**

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
- No citations in v2.

**LLM client.**
- v2 uses Gemini's free-tier Flash 2.5: fast answers, free for development. Note
  the free tier trains on submitted queries — acceptable for v2.
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
- Uses routes for a clean architecture. Four routers are mounted (`api/main.py`):
  `ingest` (`/ingest/*`), `query` (`/query/*`), `auth` (`/register`, `/login`,
  `/anonymous_login`, `/logout`, `/logout_everywhere`, `/delete_account` — see
  *Authentication & Sessions*), and `dev` (`/health`, `/admin/cleanup`).
- Deferred: document upload.
- The app listens on port **8000** inside the container; Compose publishes it on host
  **8080** (`8080:8000`).

**`dev` router: health + out-of-band sweep.**
- `GET /health` is a plain liveness string.
- `POST /admin/cleanup` runs the retention sweep (`sweep_owners` + `sweep_sessions`). It is
  gated by a `sweep-token` header compared with `secrets.compare_digest` against the
  `SWEEP_TOKEN` setting; **any** failure (missing/misconfigured token or mismatch) returns a
  bare **404**, so the endpoint is indistinguishable from a non-route to an unauthenticated
  probe. Triggered monthly by a GitHub Action (`.github/workflows/sweep.yaml`, cron `0 3 1 * *`)
  against the deployed instance; `workflow_dispatch` allows a manual run.

**Exception architecture.**
- One root, `AppError` (`rag_app/exceptions`), for every error the app raises on purpose.
  Each class carries a `status_code`, so a **single** `@app.exception_handler(AppError)`
  turns any subclass into a response (Starlette dispatches to the most specific registered
  class by MRO). Per-type handlers are therefore unnecessary and were removed.
- The tree splits by responsibility, not just by name:
  - `RagError` (4xx, client): `DocumentNotFound` (404), `EmptyDocument` (422),
    `DocumentExists` (409), `QueryTooLong` (413), and the auth errors
    `UsernameAlreadyExists` (409), `LoginUnsuccessful` (401), `InvalidSession` (401).
  - `InternalError` (5xx, invariant violations): `ChunkNotFound`, `VectorNotFound`,
    `OwnerNotFound` — these mean the data is inconsistent (a chunk with no vector, a document
    with no chunks), not that the client asked for something missing, so they are **not**
    404s. Internal-only today (no routed caller); kept for defense-in-depth.
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
- **Deployed** to Hugging Face Spaces (`https://haberric-rag-app-v1.hf.space`) against a
  managed Postgres. Deployment-specific choices (SameSite/CSRF posture on the PSL, the
  iframe-embed hole) are recorded under *Authentication & Sessions*.
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
  as `app_user` (`APP_DATABASE_URL`) — **now wired** (see *Authentication & Sessions* below).

**One clean initial migration; DB reset from scratch — no destructive op in a migration.**
- The whole schema (documents/chunks/vectors + constraints, indexes, RLS, policies, grants)
  is a single initial migration — no rename/backfill/truncate churn.
- Rationale: a `TRUNCATE` is irreversible, and
  irreversible destructive operations must not live in a migration (migrations must be
  reversible). If the DB ever holds real data before a schema change, the pattern flips to
  add-nullable → backfill → `SET NOT NULL`.

**Row-level multi-tenancy via Postgres RLS + a session GUC.**
- Shared tables with an `owner_id` discriminator on `documents` only. `chunks`/`vectors`
  isolate by **composing** through the parent's policy: their `USING`/`WITH CHECK` is a
  subselect (`document_id IN (SELECT id FROM documents)`, `chunk_id IN (SELECT id FROM
  chunks)`); the subselect is itself RLS-filtered, so a child row is visible if its
  document is. One source of truth (a single `owner_id`), no denormalized copies to keep in
  sync. Requires an index on `chunks.document_id` (added; the FK had none).
- Policies key off `current_setting('app.owner_id', true)::uuid` (`NULLIF(..., '')` folds both
  the unset-NULL and the reset-empty-string cases to NULL). Unset → **fail-closed** (rows
  hidden, writes rejected by `WITH CHECK`). The app sets this GUC **transaction-locally** per
  request via a `set_config(..., true)` in the single `set_guc` dependency (`api/deps.py`),
  which holds one `AsyncSession` (one connection, one transaction) open across the request — a
  non-local `SET` would leak tenants across pooled connections. `set_guc` **raises
  `InvalidSession` (401) when there is no owner**, so every routed request now needs a valid session (anonymous or logged in); reads no longer fall through to an empty result, they are rejected.
- **`owner_id`'s source is the `sessions` table** (see *Authentication & Sessions*). It is not
  client-supplied-and-trusted: the client sends an opaque `session_token` cookie whose SHA-256
  hash is looked up in `sessions` (`validate_session`) to resolve the owner, so a client cannot
  assert an arbitrary owner.

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
  UUID PKs are server-side.
- Boundary rule: **Alembic owns intra-database schema; bootstrap-pg.sh/infra owns databases
  and roles.** Alembic can't `CREATE DATABASE` the DB it connects to, and the role must
  pre-exist the GRANT (or the migration fails fast). Never duplicate table DDL across both.
- The credential (`users`), session (`sessions`) and owners (`owners`) tables added by the auth migration get **no
  table DML grant** at all: `app_user` reaches them only through `EXECUTE` on the
  `SECURITY DEFINER` functions (see below), never directly.

---

## Authentication & Sessions

Supersedes the earlier itsdangerous "anonymous cookie tenancy" design (dropped, along with
the `itsdangerous` dependency). Two concerns are kept separate on purpose:
**authorization** — *what content a caller may touch* — is RLS + the transaction-local
`app.owner_id` GUC + the `owners` table (above). **Authentication** — *how we verify a caller
is who they claim* — is the credential/session machinery here.

**Three-table identity model (`owners` / `users` / `sessions`).**
- `owners(id, created_at, expires_at)` is the tenancy discriminator the RLS `owner_id` keys
  off. `expires_at IS NULL` = a **registered** account (never expires); a set `expires_at` =
  an **anonymous** owner (minted with `now() + 30 days`). One `owner` per tenant.
- `users(owner_id PK → owners.id, username UNIQUE, password_hash, created_at)` holds
  **credentials** for registered accounts only. Splitting credentials off `owners` keeps the
  tenancy key free of login data and lets an anonymous owner exist with no `users` row.
- `sessions(id, token_hash UNIQUE, owner_id → owners.id, created_at, expires_at)` holds live
  sessions. All three child tables FK to `owners(id) ON DELETE CASCADE`.

**Sessions are opaque bearer tokens, verified by DB lookup — not signed.**
- A token is `secrets.token_urlsafe()`; only its **SHA-256 hash** is stored (`sessions.token_hash`),
  so a DB read can't replay a session. The raw token rides a `session_token` cookie
  (`httponly`, `samesite=lax`, `secure` per the `SECURE` setting, `max_age=cookie_expire`).
- This replaces the itsdangerous *signed* cookie: a DB-backed opaque token needs no signature
  (validity is "does this hash exist and is it unexpired", via `validate_session`), and it is
  server-side revocable (logout deletes the row) — which a stateless signed cookie is not.
- Login sessions expire after **1 day** (`create_session_login`); anonymous owner+session are
  minted together with the **30-day** window (`anonymous_mint`), so a session and its anonymous
  owner expire together.

**All auth mutations go through `SECURITY DEFINER` SQL functions (`functions.sql`, installed by
the auth migration).**
- `registration`, `login_check`, `anonymous_mint`, `create_session_login`, `validate_session`,
  `logout`, `logout_everywhere`, `delete_account`, `sweep_owners`, `sweep_sessions`. Each is
  `SECURITY DEFINER SET search_path = ''`, `REVOKE`d from `PUBLIC` and `GRANT EXECUTE`d only to
  `app_user`.
- Rationale: `app_user` has **no direct DML** on `users`/`sessions`. Forcing every touch through
  a fixed, owner-defined function surface is a "keyhole": under SQL injection it stops credential
  **exfiltration** (there is no `SELECT * FROM users` grant to abuse). Honest limit recorded in
  the DEVLOG: it does **not** stop **impersonation** — argon2 verification happens in the app, so
  the DB cannot know a password was actually checked before `create_session_login` runs; a caller
  who can already run arbitrary app SQL could mint a session without a password. Accepted for v2.
- `SET search_path = ''` forces every reference inside the function to be schema-qualified
  (`public.owners`, `pg_catalog.now()`), closing the search-path hijack that `SECURITY DEFINER`
  otherwise invites.

**Password hashing: argon2 (`argon2-cffi`), off the event loop.**
- `PasswordHasher` from argon2; hashing/verification run via `run_in_threadpool` because argon2
  is deliberately CPU-heavy and would otherwise stall the event loop. `Credentials` caps
  username ≤ 64 and password ≤ 128 chars to bound per-request argon2 work (a DoS guard, not a
  strength policy).
- **Constant-time login.** A missing username still verifies the supplied password against a
  precomputed `_DUMMY_HASH`, and every failure returns the same `LoginUnsuccessful` — no timing
  or message oracle for username enumeration.

**Endpoints.** `register` (mints owner + credentials, **no** session — must then log in),
`login` (verify argon2 → `create_session_login` → set cookie), `anonymous_login` (mint owner +
session in one call), `logout` (delete this session), `logout_everywhere` (delete all sessions
for the owner), `delete_account` (delete the owner; FK cascade removes its users/sessions and
documents→chunks→vectors). Registration and login-username races collapse to the same
`UsernameAlreadyExists` (409), guarded by the `UNIQUE(username)` constraint + `IntegrityError`.

**Retention & the FK-cascade purge.**
- `TTL` (config `timedelta`, default 30d) is the server-side retention window for anonymous
  owners; `cookie_expire` (seconds) is the browser cookie `max_age`, kept aligned to it.
- Expiry is swept **out-of-band**, not inline: `sweep_owners` deletes anonymous owners past
  `expires_at` and `sweep_sessions` deletes expired sessions. `documents.owner_id → owners.id
  ON DELETE CASCADE` means deleting an owner cascades to its documents → chunks → vectors. The
  cascade is an FK action, so it runs even though the sweeping session sets no `app.owner_id`
  (RLS/`FORCE` don't apply to FK cascades) — but *only* as an FK cascade; an app-issued
  `DELETE FROM documents` would be ordinary RLS-filtered DML and must never replace it.
- The sweep is driven by `POST /admin/cleanup` (see *dev router*), invoked monthly by a GitHub
  Action — replacing the earlier probabilistic ~10%-per-mint inline sweep.

**Deployment posture (Hugging Face Spaces / CSRF).** Recorded in the DEVLOG and load-bearing:
- All state-changing routes are **POST**; no GET ever mutates. Combined with `samesite=lax`,
  that is the CSRF defense — cheaper than a CSRF token on every request body.
- On the **direct** Space URL (`*.hf.space`), the PSL keeps other Spaces from being same-site
  siblings, so `samesite=lax` cookies work normally. The **iframe embed** is cross-site and
  would need `samesite=none` (naked to CSRF) *and* is a user/session-minting hole, so the embed
  is intentionally unsupported — the plan is a redirect/pop-out to the direct URL.
- Deferred to v3: an explicit `Origin` check as a second CSRF factor, and rate-limiting for
  `curl`/non-browser callers.

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
  RLS/policies/grants are identical.
- Two connections are available to tests: the plain `session` fixture (`raguser` — a
  superuser, bypasses RLS; used for everything not specifically testing isolation) and
  `app_session`/`tenant` (`app_user`, `app.owner_id` set for a fresh tenant — actually
  RLS-enforced, mirroring `api/deps.py`'s `set_guc`). The `Settings` fields `TEST_DATABASE_URL`
  (owner → `rag_test`) and `TEST_APP_DATABASE_URL` (`app_user` → `rag_test`) supply the two test
  URLs. RLS isolation is now testable, and `tests/test_multi_tenancy.py` exercises cross-tenant
  read/write isolation directly.
- The two test URLs reuse the same `raguser`/`app_user` passwords as the app roles (same roles,
  pointed at `rag_test`).

**CI.**
- Uses a single `compose up` (`test` profile) to stand up Postgres, then `docker compose
  run --rm pg-init` + `alembic upgrade head` (against `rag_test`) to provision and
  schema-load it, then runs host-side pytest against it — the same sequence documented
  for local runs (README *Testing*).
- Uses a committed `.env.ci` file with test credentials against a test DB.

**Dependency management: uv.**
- `uv` is the package/venv manager; `uv.lock` is committed and is the source of truth for
  exact versions. `uv sync --frozen` in CI installs from the lock (fails rather than
  re-resolving if the lock is stale).
- Dev tooling (pytest, pytest-asyncio, ruff, mypy) lives in **one** place: the PEP 735
  `[dependency-groups].dev` table, which `uv sync`/`uv run` install by default. We do *not*
  use `[project.optional-dependencies]` — having both let the two lists drift (uv reads only
  the group; the old `pip install .[dev]` read only the extra), which is what broke local
  test/lint runs. Runtime deps stay in `[project.dependencies]`.
- CI installs via `uv sync --frozen` and invokes every tool through `uv run`
  (`uv run ruff/mypy/pytest/alembic`), so CI and local use the identical resolved env.

**CPU-only torch (2026-07-22).**
- `torch` (transitive via sentence-transformers) is pinned to the CPU wheel index
  (`download.pytorch.org/whl/cpu`) via `[[tool.uv.index]]` + `[tool.uv.sources]` in
  `pyproject.toml`. Embedding runs on CPU in dev and prod; the default PyPI resolution
  pulled the CUDA 13 build — ~4.5 GB of GPU libs (torch-cu13 + `nvidia/*` + triton),
  ~3 GB of downloads — for nothing.
- Effect: ~200 MB torch download, venv 5.1 GB → 1.3 GB. `torch` is also declared in
  `[project.dependencies]` (unversioned; sentence-transformers constrains it) because the
  uv source pin does not apply to transitive-only packages.
- Consequence: installing with plain `pip install .` would still fetch the CUDA build —
  uv is the supported install path (already the case, see *Dependency management: uv*).
- Revert condition: a GPU box for embedding throughput.

---

## Deferred / Out of Scope (v1)

1. **Cross-encoder reranking of top-k.** v2 is bi-encoder retrieval only.
2. **Second CSRF factor + rate-limiting.** An explicit `Origin` check and rate-limiting for
   non-browser callers, plus a supported iframe-embed path, are deferred to v3 (see
   *Authentication & Sessions → Deployment posture*).

3. **Broader out-of-scope set for v2**: document upload.
