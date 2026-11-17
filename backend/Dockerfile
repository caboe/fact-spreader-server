# Pinned build image for the backend and worker. Python dependencies are locked in
# uv.lock; the runtime image has no compiler or package manager writes.
FROM ghcr.io/astral-sh/uv:0.9.26 AS uv

FROM python:3.12.9-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app

WORKDIR /app

COPY --from=uv /uv /uvx /bin/

COPY backend/pyproject.toml backend/uv.lock ./
# Large wheels (lingua) can outlast uv's default HTTP timeout on a slow link.
ARG UV_HTTP_TIMEOUT=600
RUN UV_HTTP_TIMEOUT=$UV_HTTP_TIMEOUT uv sync --frozen --no-dev --no-install-project

COPY backend/alembic.ini ./
COPY backend/alembic ./alembic
COPY backend/app ./app
COPY backend/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
COPY methodology /methodology
COPY tests/fixtures/corpus /tests/fixtures/corpus
COPY PERSONAS.md /PERSONAS.md
RUN chmod -R a+rX /methodology /tests/fixtures/corpus /PERSONAS.md

RUN chmod 0755 /usr/local/bin/docker-entrypoint.sh \
    && chmod 0644 pyproject.toml alembic.ini \
    && chmod -R a+rX app alembic

USER app

EXPOSE 8000

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
