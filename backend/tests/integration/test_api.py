"""API, moderation, idempotency and job-persistence guarantees (PROTOCOL §4)."""

from __future__ import annotations

from typing import Any

import app.api.v1.checks as checks_route
import app.services.checks as checks_service
import httpx
import pytest
from app.contracts.enums import JobState
from app.core.ids import new_id, utcnow
from app.db.models import Document, DocumentVersion, JobEvent
from app.db.models import Job as JobRow
from app.services.input_reader import FetchedDocument
from sqlalchemy import func, select

from tests.fakes import FakeLightRAG, FakeLLM

pytestmark = pytest.mark.integration


async def _job_count(app: Any) -> int:
    async with app.state.db.session_factory() as session:
        return int((await session.execute(select(func.count(JobRow.id)))).scalar_one())


async def _seed_approved_document(app: Any, settings: Any) -> str:
    async with app.state.db.session_factory() as session:
        document_id = new_id("doc")
        now = utcnow()
        document = Document(
            id=document_id,
            title="Integration fixture",
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
            content_hash="sha256:integration",
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
            content_hash="sha256:integration",
            content_md="Immigrants commit more crimes, according to the fixture.",
            size_bytes=64,
            created_at=now,
        )
        session.add_all([document, version])
        await session.commit()
    return document_id


@pytest.mark.asyncio
async def test_health_and_instance_are_public(client: httpx.AsyncClient) -> None:
    health = await client.get("/healthz")
    assert health.status_code == 200
    instance = await client.get("/v1/instance")
    assert instance.status_code == 200
    assert instance.json()["setup_complete"] is True


@pytest.mark.asyncio
async def test_models_require_authentication(app: Any) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as anonymous:
        response = await anonymous.get("/v1/models")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"


@pytest.mark.asyncio
async def test_usage_is_scoped_to_the_caller(client: httpx.AsyncClient) -> None:
    response = await client.get("/v1/usage/me")
    assert response.status_code == 200
    body = response.json()
    assert body["currency"] == "USD"
    assert body["budget"]["remaining_usd"] > 0


@pytest.mark.asyncio
async def test_invalid_input_is_rejected_before_a_job(client: httpx.AsyncClient) -> None:
    response = await client.post("/v1/factcheck", json={"input": {"type": "file"}})
    assert response.status_code == 422
    assert response.json()["code"] == "input_type_not_supported"


@pytest.mark.asyncio
async def test_fast_mode_is_honestly_unavailable_in_phase_1(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/factcheck",
        json={"input": {"type": "text", "text": "A claim."}, "fast": True},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "fast_mode_not_available"


@pytest.mark.asyncio
async def test_moderation_unavailable_fails_closed(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        checks_service,
        "LLMClient",
        lambda settings, consumer="pipeline": FakeLLM(unavailable=True),
    )
    response = await client.post(
        "/v1/factcheck",
        json={"input": {"type": "text", "text": "A checkable claim."}},
    )
    assert response.status_code == 503
    assert response.json()["code"] == "moderation_unavailable"


@pytest.mark.asyncio
async def test_blocked_input_creates_a_refused_result_without_a_pipeline_run(
    app: Any, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        checks_service, "LLMClient", lambda settings, consumer="pipeline": FakeLLM(block=True)
    )
    response = await client.post(
        "/v1/factcheck",
        json={"input": {"type": "text", "text": "Explicit sexual content involving a minor."}},
    )
    assert response.status_code == 202
    job_id = response.json()["job"]["id"]
    detail = await client.get(f"/v1/factcheck/{job_id}")
    assert detail.status_code == 200
    result = detail.json()["result"]["result"]
    assert result["status"] == "refused"
    assert result["moderation"]["action"] == "block"
    assert result["statements"] == []


@pytest.mark.asyncio
async def test_idempotency_key_prevents_a_second_job(
    app: Any, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        checks_service, "LLMClient", lambda settings, consumer="pipeline": FakeLLM()
    )
    body = {"input": {"type": "text", "text": "Immigrants commit more crimes."}}
    headers = {"Idempotency-Key": "integration-idempotency-1"}
    first = await client.post("/v1/factcheck", json=body, headers=headers)
    second = await client.post("/v1/factcheck", json=body, headers=headers)
    assert first.status_code == second.status_code == 202
    assert first.json()["job"]["id"] == second.json()["job"]["id"]
    assert await _job_count(app) == 1


@pytest.mark.asyncio
async def test_worker_persists_the_job_state_and_the_result(
    app: Any, client: httpx.AsyncClient, settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    document_id = await _seed_approved_document(app, settings)
    fake_llm = FakeLLM()
    monkeypatch.setattr(checks_service, "LLMClient", lambda settings, consumer="pipeline": fake_llm)
    response = await client.post(
        "/v1/factcheck",
        json={"input": {"type": "text", "text": "Immigrants commit more crimes."}},
    )
    assert response.status_code == 202
    job_id = response.json()["job"]["id"]
    async with app.state.db.session_factory() as session:
        job = await session.get(JobRow, job_id)
        assert job is not None
        await checks_service.run_check_job(
            session,
            settings=settings,
            publishers=app.state.publishers,
            methodology=app.state.methodology,
            language=app.state.language,
            lightrag=FakeLightRAG(  # type: ignore[arg-type]
                document_id=document_id,
                passage="Immigrants commit more crimes, according to the fixture.",
            ),
            personas=app.state.personas,
            job=job,
        )
        await session.commit()
    detail = await client.get(f"/v1/factcheck/{job_id}")
    assert detail.status_code == 200
    envelope = detail.json()
    assert envelope["job"]["state"] == JobState.DONE.value
    result = envelope["result"]["result"]
    assert result["status"] == "complete"
    assert result["overall_verdict"] == "true_but_misleading"
    assert result["statements"][0]["gate"]["downgraded"] is False
    assert result["evidence"][0]["provenance"]["source_quality"] == "A"
    assert result["evidence"][0]["evidence_tier"] == 1
    assert envelope["result"]["compact"]["verdict"] == "true_but_misleading"

    archive = await client.get("/v1/claims?mine=true")
    assert archive.status_code == 200
    entries = archive.json()["data"]
    assert len(entries) == 1
    assert entries[0]["result_id"] == result["id"]
    assert entries[0]["overall_verdict"] == "true_but_misleading"
    assert entries[0]["claim_text"] == "Immigrants commit more crimes."
    detail = await client.get(f"/v1/claims/{result['id']}")
    assert detail.status_code == 200
    assert detail.json()["result"]["result"]["overall_verdict"] == "true_but_misleading"
    assert detail.json()["submitted_by"] is not None

    async with app.state.db.session_factory() as event_session:
        statement = result["statements"][0]
        for sequence in (1, 2):
            event_session.add(
                JobEvent(
                    id=new_id("evt"),
                    job_id=job_id,
                    seq=sequence,
                    event_type="statement",
                    data=statement,
                    created_at=utcnow(),
                )
            )
        await event_session.commit()
    events: list[str] = []
    async with client.stream("GET", f"/v1/factcheck/{job_id}/events") as streamed:
        assert streamed.status_code == 200
        async for line in streamed.aiter_lines():
            if line.startswith("event: "):
                events.append(line[7:])
    assert events.count("statement") == 2
    assert "result" in events
    assert events[-1] == "done"
    replayed: list[str] = []
    async with client.stream(
        "GET",
        f"/v1/factcheck/{job_id}/events",
        headers={"Last-Event-ID": "1"},
    ) as streamed:
        async for line in streamed.aiter_lines():
            if line.startswith("event: "):
                replayed.append(line[7:])
    assert replayed.count("statement") == 1


@pytest.mark.asyncio
async def test_url_input_is_fetched_and_kept_out_of_the_corpus(
    app: Any, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        checks_service,
        "LLMClient",
        lambda settings, consumer="pipeline", request_id=None: FakeLLM(),
    )

    async def fake_fetch(url: str, settings: Any) -> FetchedDocument:
        return FetchedDocument(
            url="https://example.org/article",
            text="Immigrants commit more crimes.",
            title="Example",
            content_type="text/html",
            size_bytes=100,
        )

    monkeypatch.setattr(checks_route, "fetch_readable", fake_fetch)
    response = await client.post(
        "/v1/factcheck",
        json={"input": {"type": "url", "url": "https://example.org/article"}},
    )
    assert response.status_code == 202
    job_id = response.json()["job"]["id"]
    async with app.state.db.session_factory() as session:
        job = await session.get(JobRow, job_id)
        assert job is not None
        assert job.payload["text"] == "Immigrants commit more crimes."
        assert job.payload["source_url"] == "https://example.org/article"


@pytest.mark.asyncio
async def test_private_url_is_rejected_before_fetch(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post(
        "/v1/factcheck",
        json={"input": {"type": "url", "url": "http://127.0.0.1/"}},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "unsafe_url"


@pytest.mark.asyncio
async def test_a_queued_job_can_be_cancelled(
    app: Any, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        checks_service, "LLMClient", lambda settings, consumer="pipeline": FakeLLM()
    )
    response = await client.post(
        "/v1/factcheck",
        json={"input": {"type": "text", "text": "A checkable claim."}},
    )
    assert response.status_code == 202
    job_id = response.json()["job"]["id"]
    cancelled = await client.delete(f"/v1/factcheck/{job_id}")
    assert cancelled.status_code == 204
    detail = await client.get(f"/v1/factcheck/{job_id}")
    assert detail.status_code == 200
    assert detail.json()["job"]["state"] == JobState.CANCELLED.value


@pytest.mark.asyncio
async def test_markdown_file_is_parsed_and_kept_out_of_the_corpus(
    app: Any, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        checks_service,
        "LLMClient",
        lambda settings, consumer="pipeline", request_id=None: FakeLLM(),
    )
    response = await client.post(
        "/v1/factcheck",
        data={"payload": '{"input":{"type":"file","language":"en"},"response_language":"en"}'},
        files={
            "file": (
                "claim.md",
                b"# Fixture\n\nImmigrants commit more crimes.",
                "text/markdown",
            )
        },
    )
    assert response.status_code == 202, response.text
    job_id = response.json()["job"]["id"]
    async with app.state.db.session_factory() as session:
        job = await session.get(JobRow, job_id)
        assert job is not None
        assert job.payload["text"] == "# Fixture\n\nImmigrants commit more crimes."
        assert job.payload["source_file_name"] == "claim.md"
        assert job.payload["source_media_type"] == "text/markdown"
