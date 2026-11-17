"""Alembic up/down/up against a disposable Postgres with pgvector + AGE.

This is the migration gate. It uses the same image as compose and never touches the
development database.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from testcontainers.postgres import PostgresContainer

IMAGE = "pgvector/pgvector@sha256:484e838076e04939d27d3e176e91c86eea96236126023be8d3059761122e579f"


def _run(url: str, *args: str) -> None:
    env = {**os.environ, "ALEMBIC_DATABASE_URL": url}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        env=env,
        cwd=Path(__file__).resolve().parents[2],
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        print(result.stdout, file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        raise SystemExit(result.returncode)


def main() -> None:
    try:
        container = PostgresContainer(
            image=IMAGE,
            username="factspreader",
            password="migrate-check",
            dbname="app",
        )
        with container as postgres:
            raw = postgres.get_connection_url()
            url = raw.replace("postgresql+psycopg2://", "postgresql+asyncpg://").replace(
                "postgresql://", "postgresql+asyncpg://"
            )
            print("migration check: upgrade head", file=sys.stderr)
            _run(url, "upgrade", "head")
            print("migration check: downgrade base", file=sys.stderr)
            _run(url, "downgrade", "base")
            print("migration check: upgrade head again", file=sys.stderr)
            _run(url, "upgrade", "head")
            print("migration check: alembic check", file=sys.stderr)
            _run(url, "check")
    except Exception as exc:
        print(
            f"migration check could not run: {type(exc).__name__}: {exc}\n"
            "Is Docker running? The check uses the pinned pgvector image.",
            file=sys.stderr,
        )
        raise SystemExit(2) from exc
    print("migration check passed")


if __name__ == "__main__":
    main()
