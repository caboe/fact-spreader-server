#!/usr/bin/env bash
# Creates the application database (POSTGRES_DB, owned by POSTGRES_USER) and a separate
# `lightrag` database with the pgvector + Apache AGE extensions. Runs once, on an empty
# data directory. The app and the retrieval service must not share tables or roles.
set -euo pipefail

: "${POSTGRES_USER:?POSTGRES_USER is required}"
: "${POSTGRES_DB:?POSTGRES_DB is required}"
: "${LIGHTRAG_DB_USER:=lightrag}"
: "${LIGHTRAG_DB_NAME:=lightrag}"
: "${LIGHTRAG_DB_PASSWORD:?LIGHTRAG_DB_PASSWORD is required}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-SQL
    CREATE ROLE ${LIGHTRAG_DB_USER} LOGIN PASSWORD '${LIGHTRAG_DB_PASSWORD}';
    CREATE DATABASE ${LIGHTRAG_DB_NAME} OWNER ${LIGHTRAG_DB_USER};
SQL

# Extensions are created per database and need superuser rights.
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-SQL
    CREATE EXTENSION IF NOT EXISTS vector;
SQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$LIGHTRAG_DB_NAME" <<-SQL
    CREATE EXTENSION IF NOT EXISTS vector;
    CREATE EXTENSION IF NOT EXISTS age;
    LOAD 'age';
    SET search_path = ag_catalog, "\$user", public;
    SELECT create_graph('lightrag');

    -- AGE puts its functions in a schema the LightRAG role cannot see by default.
    -- Without these grants LightRAG fails on the first graph write with an error that
    -- looks like a LightRAG bug and is a missing privilege.
    GRANT USAGE ON SCHEMA ag_catalog TO ${LIGHTRAG_DB_USER};
    GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA ag_catalog TO ${LIGHTRAG_DB_USER};
    ALTER DEFAULT PRIVILEGES IN SCHEMA ag_catalog
        GRANT EXECUTE ON FUNCTIONS TO ${LIGHTRAG_DB_USER};

    -- AGE resolves its types through the search path and must be loaded per session.
    -- ag_catalog must not come first: unqualified CREATE TABLE would go there.
    ALTER ROLE ${LIGHTRAG_DB_USER} SET search_path = "\$user", public, ag_catalog;
    ALTER ROLE ${LIGHTRAG_DB_USER} SET session_preload_libraries = 'age';
    ALTER DATABASE ${LIGHTRAG_DB_NAME} SET search_path = "\$user", public, ag_catalog;
    ALTER DATABASE ${LIGHTRAG_DB_NAME} SET session_preload_libraries = 'age';
SQL
