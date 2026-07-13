#!/bin/bash
# Provision the least-privilege application role for row-level security.
#
# app_user is deliberately NOT the table owner, NOT a superuser, and has no BYPASSRLS, so
# the RLS policies (created by the Alembic migration) actually apply to it. The migration
# GRANTs it SELECT/INSERT/UPDATE/DELETE on the tables; role creation must happen first,
# hence here rather than in a migration (a role is a cluster-global object, not schema).
#
# Runs once, only on a fresh data volume (docker-entrypoint-initdb.d). Password comes from
# APP_USER_PASSWORD in the container env so no secret is baked into a checked-in file. On
# prod/Neon, create the equivalent role once via the console.
set -euo pipefail

if [ -z "${APP_USER_PASSWORD:-}" ]; then
	echo "init-app-user.sh: APP_USER_PASSWORD is not set; refusing to create app_user with an empty password" >&2
	exit 1
fi

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
	DO \$\$
	BEGIN
	    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_user') THEN
	        CREATE ROLE app_user LOGIN PASSWORD '${APP_USER_PASSWORD}';
	    END IF;
	END
	\$\$;
EOSQL
