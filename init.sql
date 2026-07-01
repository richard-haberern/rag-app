-- Runs once on first db init (mounted into /docker-entrypoint-initdb.d).
-- Creates the pgvector extension so the api can create vector columns.
CREATE EXTENSION IF NOT EXISTS vector;

-- Isolated database for the test suite (profile `test`); the app uses ragdb.
-- Only takes effect on a fresh volume; an existing volume needs a manual
-- CREATE DATABASE (see DECISIONS.md / README).
CREATE DATABASE rag_test;
\connect rag_test
CREATE EXTENSION IF NOT EXISTS vector;
