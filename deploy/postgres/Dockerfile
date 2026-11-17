FROM postgres:16.6-bookworm

# PostgreSQL 16 with the two extensions LightRAG needs for its all-in-one storage:
# pgvector (vectors) and Apache AGE (graph). Both are pinned; upgrading either one is a
# deliberate change that needs a migration rehearsal (DECISIONS.md D9).
ARG PGVECTOR_VERSION=0.8.0
ARG AGE_VERSION=PG16/v1.5.0-rc0

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        curl \
        flex \
        bison \
        git \
        libreadline-dev \
        zlib1g-dev \
        postgresql-server-dev-16; \
    curl -fsSL "https://github.com/pgvector/pgvector/archive/refs/tags/v${PGVECTOR_VERSION}.tar.gz" -o /tmp/pgvector.tar.gz; \
    mkdir -p /tmp/pgvector; \
    tar -xzf /tmp/pgvector.tar.gz -C /tmp/pgvector --strip-components=1; \
    make -C /tmp/pgvector -j"$(nproc)"; \
    make -C /tmp/pgvector install; \
    git clone --depth 1 --branch "${AGE_VERSION}" https://github.com/apache/age.git /tmp/age; \
    make -C /tmp/age -j"$(nproc)"; \
    make -C /tmp/age install; \
    apt-get purge -y --auto-remove build-essential flex bison git \
        postgresql-server-dev-16 libreadline-dev zlib1g-dev; \
    rm -rf /tmp/pgvector /tmp/age /tmp/pgvector.tar.gz /var/lib/apt/lists/*

COPY init/ /docker-entrypoint-initdb.d/
RUN chmod 0755 /docker-entrypoint-initdb.d/*.sh

HEALTHCHECK --interval=10s --timeout=5s --retries=10 \
    CMD pg_isready -U "${POSTGRES_USER:-factspreader}" -d "${POSTGRES_DB:-app}"
