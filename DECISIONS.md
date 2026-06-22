Decided stack is - FastAPI, PostgreSQL with SQLAlchemy + asyncpg, pgvector for vector storing - creating an interface that can be later easily migrated to dedicated 
vector DB (Chroma DB), local embeddings via sentence-transformers, an LLM API for generation

FastAPI 
 - for async workflow and AI oriented apps is a clear winner, already had a little bit of experience from the MINI-RAG project
 - native async 
Why not Django? 
 - not ideal for this project 
 - oriented for server-rendered pages app, batteries don't apply here
Why pgvector first instead of a Chroma DB? 
 - it simplifies the first MVP
 - create the infrastructure in a way it is easy to migrate to ChromaDB - valuable skill on its own
Local embeddings
 - don't need real big power 
 - learns more than calling an API

=========v1==============

Atomicity with pg for both of the databases is impossible if we want to migrate later. It is off the table,
we accept orphan chunks but not vectors. That means first store chunks, then vectors. For now the "orphan" chunks
is a documented-problem, which will be resolved in later versions. 

Chunk_id is code generated and not SERIAL from DB. Exists before any I/O, doesn't force the ordering (first chunk, then vector).
Vector Store holds only (chunk_id, vector) - Chroma-shaped
Retrieval in two-steps: search -> ids -> fetch text

sentence-transformer 
 - best for v1 MVP, easy, local
 - all-MiniLM-L6-v2 - fast on CPU, no GPU needed, relatively small, industry standard, not the strongest on embedding but for MVP enough, easy to swap later for better model based on MTEB
 - for similarity search we use cosine_distance - all-MiniLM-l6-v2 optimized for that

Storing just the path to a raw documnet to give the user
Later use cross-encoders for better retrieval - not in a v1

Two method in embedding class
 - many tranformers use different one for each one so for future replacement is better to use this interface
 - one embedd_document 
 - one embedd_query

Seperate chunk_store, doc_store, vector_store (swappable).
 - we need positon in chunk mapping -> better for LLM generation when we retrive topk elements

No ORM objects leaving the session - problem with detached objects
 - we return DTOs
 - extra mapping ORM -> DTO 


init_db()
 - will have privileges problems with the pgvector extension the moment it leaves container 
 - create_all - doesn't track schema changes - if add column etc. doesn't change the tables
 - for dev - drop and recreate

doc_metadata in Document is a dict of `str` and `Any`, the key always has to be `str`

No vector index for fast top-k retrieval search, deferred
 - brute force for now - implement later

In pyproject.toml we have lower_bound >= for the packages -> if a future package changes something we won't work
for future pin with lockfile


Deffered:
1. ANN index (HNSW/ivfflat) 
  - search is brute-force (sequential scan + cosine_distance ORDER BY) 
  - add an index when row counts and query latency justify the build/tuning cost.
2. create_all → Alembic
  - create_all only creates missing tables; it never ALTERs an existing one
  - model change silently leaves the live table on the old schema. 
  - Dev workaround = drop + recreate
3. pgvector extension privileges
  - CREATE EXTENSION needs a privileged role
  - fine in local container
  - deployment time concern - must be pre-enbaled / a priviliged role
4. Cross-encoder reranking of top-k
  - v1 - bi-encoder retrieval only for now
5. Orphan chunks — accepted
  - no reconciliation / cleanup job
  - orphan vectors - prevented in store-orchestration (not yet implemented)
6. Abstract VectorStore/Embedder Protocol for the ChromaDB swap 
  - right now the seam is concrete classes with compatible shapes, not a formal interface. 
  - the chunk_vectors→chunks FK is pgvector-only and won't port to Chroma
7. The whole HTTP + generation layer — FastAPI ingest/query endpoints and the LLM API client. Plus created_at/audit columns. 
   and the broader out-of-scope set for v1: auth, streaming, multiple collections.


=========v1 implementation (CC plumbing)==============

- Vector model PK renamed id -> chunk_id (matches "(chunk_id, vector)"); one vector per chunk.
- stored_vectors keeps a FK -> stored_chunks(chunk_id) ON DELETE CASCADE. NOTE: this FK is
  pgvector-only — it couples the store to Postgres and will NOT carry over to a ChromaDB store.
  It buys referential integrity + cascade deletes, not the search() return shape.
- Chunk: position (int) + UniqueConstraint(document_id, position).
- Document: JSONB metadata column (ORM attribute doc_metadata; 'metadata' is reserved by SQLAlchemy's
  declarative registry). Raw document still stored as a filesystem path.
- pgvector column dimension from one config value EMBED_DIM=384 -> single source of truth.
- Stores accept/return DTOs (DocumentDTO, ChunkDTO)/primitives, never ORM objects.
- One shared async engine + async_sessionmaker(expire_on_commit=False); DB creds from .env (DATABASE_URL).
- init_db(): CREATE EXTENSION vector + metadata.create_all. Alembic deferred.

- Deferred: ANN index (ivfflat/hnsw), abstract VectorStore/Embedder Protocols, created_at, FastAPI endpoint.//





Store Orchestrator - Ingestion Service
 - when inserting a document the embedder blocks the whole event loop - we accept that in v1
 - deffered: asyncio.to_thread


Retrieval Service
 - deffered: threshold to searchk - filter, re-rank with cross-encoder

Prompt Builder
 - no citations for v1

LLM Client
 - for v1 we use Gemini's free tier Flash 2.5 for fast answers and free tier for development
 - the client is swappable
 - we prompt the LLM through httpx without taking another dependency on anthropic / openai... package
 - the free tier uses the queries for training - for v1 fine
 - we use AsyncClient for the session pools because we do the same https call over and over again 
 - AsyncClient is injected - expensive, more testable, follows the projects architecture
 - not owned by LLMClient, owned by caller

FastAPI
 - documents accpted as JSONs - no document parsing 
 - used routes for clean architecture 

FastAPI deferred
 - upload documents 
