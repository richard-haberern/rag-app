-- Runs once on first db init (mounted into /docker-entrypoint-initdb.d).
-- The pgvector extension is NOT created here: the app always creates it on boot
-- (init_db, src/rag_app/db/bootstrap.py), and the test suite creates it in its
-- setup_schema fixture.

-- Isolated database for the test suite (profile `test`); the app uses ragdb.
-- Only takes effect on a fresh volume; an existing volume needs a manual
-- CREATE DATABASE (see DECISIONS.md / README).
CREATE DATABASE rag_test;
