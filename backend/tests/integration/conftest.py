"""Integration fixtures: disposable Postgres, app lifespan and a seeded API key.

The API tests do not need LightRAG or a provider; the model and retrieval boundaries are
replaced with the deterministic fakes in ``tests/fakes.py``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
from app.cli import bootstrap
from app.contracts.enums import PERMISSIONS
from app.core.config import Settings
from app.db.base import Base
from app.db.models import User
from app.db.session import Database
from app.main import create_app
from app.services.auth import create_api_key
from pydantic import SecretStr
from sqlalchemy import select, text
from testcontainers.postgres import PostgresContainer

from tests.fakes import FakeEmbedder

pytestmark = pytest.mark.integration


@pytest.fixture(scope="session")
def postgres() -> Iterator[str]:
    container = PostgresContainer(
        "pgvector/pgvector@sha256:484e838076e04939d27d3e176e91c86eea96236126023be8d3059761122e579f",
        username="factspreader",
        password="test-password",
        dbname="app",
    )
    with container as running:
        url = running.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql+asyncpg://"
        )
        yield url


@pytest.fixture()
async def settings(postgres: str) -> Settings:
    return Settings(
        app_env="test",
        database_url=postgres,
        redis_url="redis://127.0.0.1:6399/15",
        app_secret_key=SecretStr("test-app-secret-" + "x" * 32),
        internal_llm_key=SecretStr("test-internal-key"),
        setup_token=SecretStr("test-setup-token"),
        lightrag_internal_key=SecretStr("test-lightrag-key"),
        deepseek_api_key=SecretStr("test-provider-key"),
        bootstrap_admin_email="admin@test.invalid",
        bootstrap_admin_password=SecretStr("test-admin-password"),
        publisher_list_path="../methodology/publishers.json",
        checklist_dir="../methodology/checklists",
        pattern_list_path="../methodology/patterns.json",
        fixture_corpus_dir="../tests/fixtures/corpus",
        supported_languages=["en", "de", "fr", "es"],
    )


@pytest.fixture()
async def app(settings: Settings) -> AsyncIterator[object]:
    database = Database(settings)
    async with database.engine.begin() as connection:
        await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    await database.dispose()
    await bootstrap(settings, print_api_key=False)
    application = create_app(settings)
    async with application.router.lifespan_context(application):
        # Research and /retrieval embed through the gateway; the suite never does.
        application.state.embedder = FakeEmbedder()  # type: ignore[attr-defined]
        yield application


@pytest.fixture()
async def api_key(app: object, settings: Settings) -> str:
    database = Database(settings)
    async with database.session_factory() as session:
        user = (
            await session.execute(select(User).where(User.email == settings.bootstrap_admin_email))
        ).scalar_one()
        assert user.permissions == list(PERMISSIONS)
        _row, plaintext = await create_api_key(
            session, user=user, name="integration-test", permissions=list(PERMISSIONS)
        )
        await session.commit()
    await database.dispose()
    return plaintext


@pytest.fixture()
async def client(app: object, api_key: str) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {api_key}"},
    ) as http:
        yield http
