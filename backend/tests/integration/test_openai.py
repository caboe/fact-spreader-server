"""OpenAI-compatible adapter and checked streaming (PROTOCOL §6)."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import app.services.checks as checks_service
import httpx
import pytest
from app.core.ids import new_id, utcnow
from app.db.models import Document, DocumentVersion
from app.db.models import Job as JobRow
from app.services.checks import run_check_job
from sqlalchemy import select

from tests.fakes import FakeLightRAG, FakeLLM

pytestmark = pytest.mark.integration

ANALYST_NARRATIVE = "Verdict: True, but misleading. The raw figure is supported [E1]."


async def _seed_document(app: Any) -> str:
    async with app.state.db.session_factory() as session:
        document_id = new_id("doc")
        now = utcnow()
        document = Document(
            id=document_id,
            title="OpenAI integration fixture",
            publisher="Federal Criminal Police Office (BKA)",
            authors=[],
            publication_date=None,
            url=None,
            doi=None,
            dataset_id=None,
            source_quality="A",
            source_quality_basis={"source": "shipped_list", "entry": "bka"},
            domain_tags=["racism"],
            language="en",
            license="CC0-1.0",
            redistribution="full_text",
            origin_instance_id="inst_test",
            origin_document_id=document_id,
            content_hash="sha256:openai-integration",
            state="indexed",
            version=1,
            approved_at=now,
            deleted=False,
            created_at=now,
            updated_at=now,
        )
        version = DocumentVersion(
            id=new_id("ver"),
            document_id=document_id,
            version=1,
            content_hash="sha256:openai-integration",
            content_md="Registered suspects are higher in the raw comparison.",
            size_bytes=64,
            created_at=now,
        )
        session.add_all([document, version])
        await session.commit()
    return document_id


async def _process_one(app: Any, settings: Any, document_id: str, fake: FakeLLM) -> None:
    for _ in range(200):
        async with app.state.db.session_factory() as session:
            job = (
                await session.execute(
                    select(JobRow)
                    .where(JobRow.state == "queued")
                    .order_by(JobRow.created_at)
                    .limit(1)
                )
            ).scalar_one_or_none()
            if job is not None:
                await run_check_job(
                    session,
                    settings=settings,
                    publishers=app.state.publishers,
                    methodology=app.state.methodology,
                    language=app.state.language,
                    lightrag=FakeLightRAG(  # type: ignore[arg-type]
                        document_id=document_id,
                        passage="Registered suspects are higher in the raw comparison.",
                    ),
                    personas=app.state.personas,
                    job=job,
                )
                await session.commit()
                return
        await asyncio.sleep(0.05)
    raise AssertionError("no queued job appeared")


def _patch_llm(monkeypatch: pytest.MonkeyPatch, fake: FakeLLM) -> None:
    monkeypatch.setattr(
        checks_service,
        "LLMClient",
        lambda settings, consumer="pipeline", request_id=None: fake,
    )


@pytest.mark.asyncio
async def test_models_list_personas_and_none(client: httpx.AsyncClient) -> None:
    response = await client.get("/v1/models")
    assert response.status_code == 200
    ids = {item["id"] for item in response.json()["data"]}
    assert {
        "factcheck",
        "factcheck:analyst",
        "factcheck:mediator",
        "factcheck:straight-talker",
        "factcheck:none",
    } <= ids


@pytest.mark.asyncio
async def test_non_streaming_persona_check(
    app: Any, client: httpx.AsyncClient, settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    document_id = await _seed_document(app)
    fake = FakeLLM(narratives=[ANALYST_NARRATIVE])
    _patch_llm(monkeypatch, fake)
    task = asyncio.create_task(_process_one(app, settings, document_id, fake))
    response = await client.post(
        "/v1/chat/completions",
        json={
            "model": "factcheck:analyst",
            "messages": [{"role": "user", "content": "Immigrants commit more crimes."}],
        },
    )
    await task
    assert response.status_code == 200
    payload = response.json()
    assert payload["choices"][0]["message"]["content"] == ANALYST_NARRATIVE
    assert payload["factcheck"]["result"]["overall_verdict"] == "true_but_misleading"
    assert payload["factcheck"]["rendering"]["consistency"]["passed"] is True
    assert payload["factcheck"]["compact"]["verdict"] == "true_but_misleading"


@pytest.mark.asyncio
async def test_factcheck_none_returns_the_deterministic_substance(
    app: Any, client: httpx.AsyncClient, settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    document_id = await _seed_document(app)
    fake = FakeLLM()
    _patch_llm(monkeypatch, fake)
    task = asyncio.create_task(_process_one(app, settings, document_id, fake))
    response = await client.post(
        "/v1/chat/completions",
        json={
            "model": "factcheck:none",
            "messages": [{"role": "user", "content": "Immigrants commit more crimes."}],
        },
    )
    await task
    assert response.status_code == 200
    payload = response.json()
    assert payload["factcheck"]["rendering"] is None
    assert payload["factcheck"]["result"]["overall_verdict"] == "true_but_misleading"
    assert payload["choices"][0]["message"]["content"]


@pytest.mark.asyncio
async def test_streaming_sends_the_result_before_any_content(
    app: Any, client: httpx.AsyncClient, settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    document_id = await _seed_document(app)
    fake = FakeLLM(narratives=[ANALYST_NARRATIVE])
    _patch_llm(monkeypatch, fake)
    task = asyncio.create_task(_process_one(app, settings, document_id, fake))
    chunks: list[dict[str, Any]] = []
    async with client.stream(
        "POST",
        "/v1/chat/completions",
        json={
            "model": "factcheck:analyst",
            "messages": [{"role": "user", "content": "Immigrants commit more crimes."}],
            "stream": True,
            "stream_options": {"include_usage": True},
        },
    ) as response:
        assert response.status_code == 200
        async for line in response.aiter_lines():
            if not line.startswith("data: ") or line == "data: [DONE]":
                continue
            data = json.loads(line[6:])
            if "error" in data:
                raise AssertionError(data["error"])
            chunks.append(data)
    await task
    assert chunks
    assert chunks[0]["choices"][0]["delta"] == {}
    assert "factcheck" in chunks[0]
    content = "".join(chunk["choices"][0]["delta"].get("content", "") for chunk in chunks)
    assert content == ANALYST_NARRATIVE
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop"
    assert chunks[-1]["usage"]["total_tokens"] >= 0


@pytest.mark.asyncio
async def test_unsupported_openai_parameters_use_the_openai_error_shape(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post(
        "/v1/chat/completions",
        json={
            "model": "factcheck:analyst",
            "messages": [{"role": "user", "content": "A claim."}],
            "tools": [],
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unsupported_parameter"


@pytest.mark.asyncio
async def test_a_blocked_openai_request_returns_a_refusal(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeLLM(block=True)
    _patch_llm(monkeypatch, fake)
    response = await client.post(
        "/v1/chat/completions",
        json={
            "model": "factcheck:none",
            "messages": [{"role": "user", "content": "Explicit sexual content involving a minor."}],
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["choices"][0]["finish_reason"] == "content_filter"
    assert payload["factcheck"]["result"]["status"] == "refused"


@pytest.mark.asyncio
async def test_conversation_history_is_preserved_as_context(
    app: Any, client: httpx.AsyncClient, settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    document_id = await _seed_document(app)
    fake = FakeLLM(narratives=[ANALYST_NARRATIVE])
    _patch_llm(monkeypatch, fake)
    task = asyncio.create_task(_process_one(app, settings, document_id, fake))
    response = await client.post(
        "/v1/chat/completions",
        json={
            "model": "factcheck:analyst",
            "messages": [
                {"role": "user", "content": "Earlier question."},
                {"role": "assistant", "content": "Earlier answer."},
                {"role": "user", "content": "Immigrants commit more crimes."},
            ],
        },
    )
    await task
    assert response.status_code == 200
    result = response.json()["factcheck"]["result"]
    assert result["input"]["context"]["messages"][0]["content"] == "Earlier question."
    assert result["turn_type"] == "follow_up_claim"
