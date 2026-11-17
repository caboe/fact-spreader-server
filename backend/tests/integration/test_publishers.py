"""A local publisher override re-grades retrieval and lists affected cache entries."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from app.core.ids import new_id, utcnow
from app.db.models import ClaimCache, Document, DocumentVersion, Instance
from app.db.models import Job as JobRow
from app.services import checks as checks_service
from app.services.publisher_overrides import effective_publishers
from sqlalchemy import select

from tests.fakes import FakeLightRAG, FakeLLM

pytestmark = pytest.mark.integration

PUBLISHER = "Federal Criminal Police Office (BKA)"
PASSAGE = "The police recorded 100 suspects, not 100 convictions."


async def _seed_document(app: Any) -> str:
    async with app.state.db.session_factory() as session:
        document_id = new_id("doc")
        now = utcnow()
        session.add(
            Document(
                id=document_id,
                title="BKA fixture",
                publisher=PUBLISHER,
                authors=[],
                source_quality="A",
                source_quality_basis={"source": "shipped_list", "entry": "bka"},
                domain_tags=["crime"],
                language="en",
                license="CC0-1.0",
                redistribution="full_text",
                origin_instance_id="inst_test",
                origin_document_id=document_id,
                content_hash="sha256:publisher",
                state="indexed",
                version=1,
                approved_at=now,
                deleted=False,
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            DocumentVersion(
                id=new_id("ver"),
                document_id=document_id,
                version=1,
                content_hash="sha256:publisher",
                content_md=PASSAGE,
                size_bytes=len(PASSAGE),
                created_at=now,
            )
        )
        await session.commit()
    return document_id


@pytest.mark.asyncio
async def test_override_changes_a_new_retrieval_and_reports_the_cached_impact(
    client: httpx.AsyncClient, app: Any, settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    overridden = await client.put(
        "/v1/config/publishers/overrides",
        json={"entries": [{"key": "bka", "grade": "D"}]},
    )
    assert overridden.status_code == 200, overridden.text
    assert "+local:" in overridden.json()["effective_version"]

    changes = await client.get("/v1/config/publishers/diff")
    assert {"key": "bka", "field": "grade", "shipped": "A", "local": "D"}.items() <= changes.json()[
        0
    ].items()
    resolved = await client.post("/v1/config/publishers/resolve", json={"publisher": "BKA"})
    assert resolved.json()["grade"] == "D"
    assert resolved.json()["basis"]["source"] == "local_list"

    document_id = await _seed_document(app)
    fake_llm = FakeLLM()
    monkeypatch.setattr(checks_service, "LLMClient", lambda settings, consumer="pipeline": fake_llm)
    submitted = await client.post(
        "/v1/factcheck",
        json={"input": {"type": "text", "text": "Suspects are not convictions."}},
    )
    assert submitted.status_code == 202, submitted.text
    job_id = submitted.json()["job"]["id"]
    async with app.state.db.session_factory() as session:
        job = await session.get(JobRow, job_id)
        assert job is not None
        await checks_service.run_check_job(
            session,
            settings=settings,
            publishers=await effective_publishers(session, settings.publisher_list_path),
            methodology=app.state.methodology,
            language=app.state.language,
            lightrag=FakeLightRAG(document_id=document_id, passage=PASSAGE),  # type: ignore[arg-type]
            personas=app.state.personas,
            job=job,
        )
        await session.commit()
    detail = (await client.get(f"/v1/factcheck/{job_id}")).json()
    evidence = detail["result"]["result"]["evidence"]
    assert evidence, detail
    provenance = evidence[0]["provenance"]
    assert provenance["source_quality"] == "D"
    assert provenance["source_quality_basis"]["source"] == "local_list"
    result_id = detail["result"]["result"]["id"]

    async with app.state.db.session_factory() as session:
        instance = (await session.execute(select(Instance).limit(1))).scalar_one()
        session.add(
            ClaimCache(
                id=new_id("cch"),
                normalized_text="suspects are not convictions",
                embedding=[1.0] + [0.0] * 1023,
                result_id=result_id,
                corpus_version=instance.corpus_version,
                language="en",
                created_at=utcnow(),
            )
        )
        await session.commit()
    impact = await client.get("/v1/config/publishers/impact")
    assert impact.status_code == 200, impact.text
    assert any(entry["result_id"] == result_id for entry in impact.json())
    assert any(PUBLISHER in entry["publishers"] for entry in impact.json())

    restored = await client.put("/v1/config/publishers/overrides", json={"entries": []})
    assert restored.status_code == 200
    assert restored.json()["effective_version"] == restored.json()["version"]
