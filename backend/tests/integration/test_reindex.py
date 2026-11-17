"""Explicit re-index: confirmation, lock, rebuild jobs and retryable state."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from app.core.ids import new_id, utcnow
from app.db.models import AuditLog, Document, DocumentVersion, ModelRecord, Setting
from app.db.models import Job as JobRow
from app.llm.aliases import FS_EMBEDDING
from app.services.reindex import run_reindex_job
from sqlalchemy import select

from tests.fakes import FakeLightRAG

pytestmark = pytest.mark.integration


async def _seed_indexed_documents(app: Any, count: int = 2) -> list[str]:
    ids: list[str] = []
    async with app.state.db.session_factory() as session:
        for index in range(count):
            document_id = new_id("doc")
            now = utcnow()
            session.add(
                Document(
                    id=document_id,
                    title=f"Approved {index}",
                    publisher="Example Publisher",
                    authors=[],
                    source_quality="B",
                    source_quality_basis={"source": "shipped_list"},
                    domain_tags=[],
                    language="en",
                    license="CC0-1.0",
                    redistribution="full_text",
                    origin_instance_id="inst_test",
                    origin_document_id=document_id,
                    content_hash=f"sha256:reindex-{index}",
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
                    content_hash=f"sha256:reindex-{index}",
                    content_md=f"Approved content {index}.",
                    size_bytes=20,
                    created_at=now,
                )
            )
            ids.append(document_id)
        await session.commit()
    return ids


@pytest.mark.asyncio
async def test_reindex_requires_confirmation_deletes_sources_and_queues_index_jobs(
    client: httpx.AsyncClient, app: Any
) -> None:
    document_ids = await _seed_indexed_documents(app)
    refused = await client.post("/v1/config/reindex", json={"confirm": False})
    assert refused.status_code == 422
    assert refused.json()["code"] == "reindex_confirmation_required"

    accepted = await client.post(
        "/v1/config/reindex", json={"confirm": True, "reason": "phase 6 test"}
    )
    assert accepted.status_code == 202, accepted.text
    body = accepted.json()
    assert body["documents"] == len(document_ids)
    assert body["embedding_model_id"]
    async with app.state.db.session_factory() as session:
        embedding = (
            await session.execute(
                select(ModelRecord).where(ModelRecord.gateway_alias == FS_EMBEDDING)
            )
        ).scalar_one()
        lock = await session.get(Setting, "corpus.embedding_model")
        assert lock is not None
        assert lock.value["model_id"] == embedding.id
        job = await session.get(JobRow, body["job_id"])
        assert job is not None and job.state == "queued"

    fake_lightrag = FakeLightRAG(document_id=document_ids[0], passage="x")
    fake_lightrag.inserted = [
        {"content": "old", "file_source": f"{document_id}@v1", "title": "old"}
        for document_id in document_ids
    ]
    async with app.state.db.session_factory() as session:
        job = await session.get(JobRow, body["job_id"])
        assert job is not None
        await run_reindex_job(
            session,
            settings=app.state.settings,
            lightrag=fake_lightrag,
            job=job,  # type: ignore[arg-type]
        )
        await session.commit()
    assert set(fake_lightrag.deleted) == {
        f"doc-lightrag-{index}" for index in range(len(document_ids))
    }
    async with app.state.db.session_factory() as session:
        documents = (
            (await session.execute(select(Document).where(Document.id.in_(document_ids))))
            .scalars()
            .all()
        )
        assert {document.state for document in documents} == {"approved"}
        index_jobs = (
            (
                await session.execute(
                    select(JobRow).where(
                        JobRow.kind == "document_index",
                        JobRow.state == "queued",
                        JobRow.payload["reindex"].astext == "true",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(index_jobs) == len(document_ids)
        job = await session.get(JobRow, body["job_id"])
        assert job is not None
        assert job.state == "done"
        assert job.progress == 1.0
        audit = (
            (await session.execute(select(AuditLog).where(AuditLog.action == "reindex_requested")))
            .scalars()
            .all()
        )
        assert len(audit) == 1

    status = await client.get(f"/v1/config/reindex/{body['job_id']}")
    assert status.status_code == 200, status.text
    assert status.json()["state"] == "done"
    assert status.json()["documents"] == len(document_ids)


@pytest.mark.asyncio
async def test_a_changed_embedding_model_is_recorded_by_the_explicit_reindex(
    client: httpx.AsyncClient, app: Any
) -> None:
    await _seed_indexed_documents(app, count=1)
    async with app.state.db.session_factory() as session:
        embedding = (
            await session.execute(
                select(ModelRecord).where(ModelRecord.gateway_alias == FS_EMBEDDING)
            )
        ).scalar_one()
        lock = await session.get(Setting, "corpus.embedding_model")
        value = {
            "model_id": "mdl_stale",
            "alias": FS_EMBEDDING,
            "dimension": embedding.embedding_dim,
        }
        if lock is None:
            session.add(Setting(key="corpus.embedding_model", value=value, updated_at=utcnow()))
        else:
            lock.value = value
            lock.updated_at = utcnow()
        await session.commit()
    accepted = await client.post("/v1/config/reindex", json={"confirm": True})
    assert accepted.status_code == 202, accepted.text
    assert accepted.json()["model_changed"] is True
    async with app.state.db.session_factory() as session:
        embedding = (
            await session.execute(
                select(ModelRecord).where(ModelRecord.gateway_alias == FS_EMBEDDING)
            )
        ).scalar_one()
        lock = await session.get(Setting, "corpus.embedding_model")
        assert lock is not None
        assert lock.value["model_id"] == embedding.id
        audit = (
            (
                await session.execute(
                    select(AuditLog).where(AuditLog.action == "embedding_model_changed")
                )
            )
            .scalars()
            .all()
        )
        assert len(audit) == 1
