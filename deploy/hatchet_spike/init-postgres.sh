#!/bin/sh
set -eu

: "${HATCHET_DATABASE_PASSWORD:?required}"
: "${PRODUCT_MIGRATOR_PASSWORD:?required}"
: "${PRODUCT_APP_PASSWORD:?required}"

psql --set=ON_ERROR_STOP=1 \
    --username "$POSTGRES_USER" \
    --dbname "$POSTGRES_DB" \
    --set=hatchet_password="$HATCHET_DATABASE_PASSWORD" \
    --set=migrator_password="$PRODUCT_MIGRATOR_PASSWORD" \
    --set=app_password="$PRODUCT_APP_PASSWORD" <<'SQL'
SELECT format('CREATE ROLE hatchet LOGIN PASSWORD %L', :'hatchet_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'hatchet')
\gexec

SELECT format(
    'CREATE ROLE benchmark_migrator LOGIN PASSWORD %L',
    :'migrator_password'
)
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'benchmark_migrator')
\gexec

SELECT format('CREATE ROLE benchmark_app LOGIN PASSWORD %L', :'app_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'benchmark_app')
\gexec

SELECT 'CREATE DATABASE hatchet OWNER hatchet'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'hatchet')
\gexec

SELECT 'CREATE DATABASE benchmark_control OWNER benchmark_migrator'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'benchmark_control')
\gexec

REVOKE CONNECT, TEMPORARY ON DATABASE hatchet FROM PUBLIC;
REVOKE CONNECT, TEMPORARY ON DATABASE benchmark_control FROM PUBLIC;
GRANT CONNECT, TEMPORARY ON DATABASE hatchet TO hatchet;
GRANT CONNECT ON DATABASE benchmark_control TO benchmark_migrator, benchmark_app;
SQL

psql --set=ON_ERROR_STOP=1 \
    --username "$POSTGRES_USER" \
    --dbname benchmark_control <<'SQL'
GRANT CONNECT ON DATABASE benchmark_control TO benchmark_app;
GRANT USAGE ON SCHEMA public TO benchmark_app;
ALTER DEFAULT PRIVILEGES FOR ROLE benchmark_migrator IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO benchmark_app;
ALTER DEFAULT PRIVILEGES FOR ROLE benchmark_migrator IN SCHEMA public
    GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO benchmark_app;
SQL
