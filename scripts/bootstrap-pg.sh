#!/bin/bash
# Idempotent Postgres bootstrap: creates the isolated rag_test database and the
# least-privilege app_user role if either is missing. Safe to run any number of
# times against any pg volume (fresh or years-old) -- unlike docker-entrypoint-initdb.d
# scripts, which Postgres only runs once, on a brand-new volume.
#
# Run via `docker compose run --rm pg-init` after `pg` is healthy, before
# `alembic upgrade head` / the app / the test suite.
#
# Connection is via PG* env vars (PGHOST/PGUSER/PGPASSWORD/PGDATABASE), set by the
# pg-init service in docker-compose.yaml.
set -euo pipefail

# rag_test: isolated database for the test suite; the app itself uses ragdb.
# CREATE DATABASE has no IF NOT EXISTS, hence the existence check.
exists=$(psql -tAc "SELECT 1 FROM pg_database WHERE datname = 'rag_test'")
if [ "$exists" != "1" ]; then
	psql -v ON_ERROR_STOP=1 -c "CREATE DATABASE rag_test"
fi

# app_user: the least-privilege role the running app (and app_session test fixtures)
# connect as, so RLS policies (created by the Alembic migration) actually apply. Not
# the table owner, not a superuser, no BYPASSRLS. A role is cluster-global, so this
# only needs to run once per cluster, not once per database.
if [ -z "${APP_USER_PASSWORD:-}" ]; then
	echo "bootstrap-pg.sh: APP_USER_PASSWORD is not set; refusing to create app_user with an empty password" >&2
	exit 1
fi

psql -v ON_ERROR_STOP=1 <<-EOSQL
	DO \$\$
	BEGIN
	    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_user') THEN
	        CREATE ROLE app_user LOGIN PASSWORD '${APP_USER_PASSWORD}';
	    END IF;
	END
	\$\$;
EOSQL
