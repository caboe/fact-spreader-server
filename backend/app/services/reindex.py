"""Explicit corpus re-index (IMPLEMENT Phase 6, PROTOCOL §12.4).

Only an approved document enters LightRAG, so a re-index is planned from approved
(indexed) documents, deletes their `doc@v` sources and enqueues one `document_index` job
per document. The embedding-model lock is moved only by this explicit, confirmed action;
there is no LightRAG index backup, because the approved documents are the source of truth.
The job is retryable: documents are set back to `approved` before the index jobs are
enqueued, so a crash after the lock change leaves a clear recovery path.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.core.ids import new_id, utcnow
from app.db.models import AuditLog, Document, DocumentVersion, ModelRecord, Setting
from app.db.models import Job as JobRow
from app.llm.aliases import FS_EMBEDDING
from app.retrieval.lightrag import LightRAGClient

logger = logging.getLogger(__name__)
TERMINAL_STATES = ("failed", "cancelled")


async def _embedding_model(session: AsyncSession) -> ModelRecord | None:
    return (
        await session.execute(
            select(ModelRecord).where(
                ModelRecord.gateway_alias == FS_EMBEDDING, ModelRecord.enabled.is_(True)
            )
        )
    ).scalar_one_or_none()


def _lock_matches(lock: Setting | None, model: ModelRecord | None) -> bool:
    if lock is None or model is None:
        return lock is None and model is None
    value = lock.value if isinstance(lock.value, dict) else {}
    return value.get("model_id") == model.id


async def plan_reindex(
    session: AsyncSession, settings: Settings
) -> tuple[list[Document], ModelRecord | None, bool]:
    documents = (
        (
            await session.execute(
                select(Document).where(
                    Document.deleted.is_(False), Document.state.in_(["approved", "indexed"])
                )
            )
        )
        .scalars()
        .all()
    )
    embedding = await _embedding_model(session)
    lock = await session.get(Setting, "corpus.embedding_model")
    changed = embedding is not None and not _lock_matches(lock, embedding)
    return list(documents), embedding, changed


async def create_reindex_job(
    session: AsyncSession,
    settings: Settings,
    *,
    user_id: str | None,
    reason: str | None,
    confirm: bool,
) -> tuple[JobRow, int, str | None, bool]:
    if not confirm:
        raise AppError(
            422,
            "reindex_confirmation_required",
            "A re-index deletes and rebuilds the LightRAG index; pass confirm=true.",
        )
    documents, embedding, changed = await plan_reindex(session, settings)
    if not documents:
        raise AppError(409, "no_approved_documents", "There are no approved documents to index.")
    now = utcnow()
    if embedding is not None:
        lock = await session.get(Setting, "corpus.embedding_model")
        value = {
            "model_id": embedding.id,
            "alias": embedding.gateway_alias,
            "dimension": embedding.embedding_dim,
        }
        if lock is None:
            session.add(Setting(key="corpus.embedding_model", value=value, updated_at=now))
        else:
            lock.value = value
            lock.updated_at = now
        if changed:
            session.add(
                AuditLog(
                    id=new_id("aud"),
                    actor_id=user_id,
                    actor_type="user" if user_id else "system",
                    action="embedding_model_changed",
                    object_type="model",
                    object_id=embedding.id,
                    detail={"alias": FS_EMBEDDING, "model": embedding.model_name},
                    created_at=now,
                )
            )
    job = JobRow(
        id=new_id("job"),
        kind="reindex",
        state="queued",
        payload={
            "document_ids": [document.id for document in documents],
            "reason": reason or "manual",
            "embedding_model_id": embedding.id if embedding else None,
            "model_changed": changed,
        },
        progress=0.0,
        user_id=user_id,
        created_at=now,
    )
    session.add(job)
    savepoint = await session.begin_nested()
    try:
        await savepoint.commit()
    except Exception:  # pragma: no cover - defensive
        await savepoint.rollback()
    session.add(
        AuditLog(
            id=new_id("aud"),
            actor_id=user_id,
            actor_type="user" if user_id else "system",
            action="reindex_requested",
            object_type="job",
            object_id=job.id,
            detail={"documents": len(documents), "model_changed": changed},
            created_at=now,
        )
    )
    await session.commit()
    return job, len(documents), embedding.id if embedding else None, changed


async def run_reindex_job(
    session: AsyncSession,
    *,
    settings: Settings,
    lightrag: LightRAGClient,
    job: JobRow,
) -> None:
    payload = job.payload or {}
    document_ids = [str(doc_id) for doc_id in payload.get("document_ids") or []]
    if not document_ids:
        raise ValueError("reindex_has_no_documents")
    documents = (
        (
            await session.execute(
                select(Document).where(Document.id.in_(document_ids), Document.deleted.is_(False))
            )
        )
        .scalars()
        .all()
    )
    versions = {
        row.document_id: row.version
        for row in (
            await session.execute(
                select(DocumentVersion)
                .where(DocumentVersion.document_id.in_(document_ids))
                .order_by(DocumentVersion.version)
            )
        ).scalars()
    }
    job.state = "running"
    job.started_at = utcnow()
    job.locked_at = utcnow()
    await session.commit()

    sources = [
        f"{document.id}@v{versions.get(document.id, document.version)}" for document in documents
    ]
    if sources:
        try:
            await lightrag.delete_by_file_source(sources)
            await lightrag.wait_until_sources_absent(sources)
        except Exception:
            # A source missing from LightRAG must not stop the rebuild: the insert below
            # recreates it and the resulting index is the same.
            logger.warning("reindex_delete_failed", extra={"event": "reindex"})
    # Queued document_index jobs wait on their own tracks; a global idle wait here would
    # block the operator job behind unrelated documents (DECISIONS.md D73).
    now = utcnow()
    for index, document in enumerate(documents, start=1):
        document.state = "approved"
        document.updated_at = now
        session.add(
            JobRow(
                id=new_id("job"),
                kind="document_index",
                state="queued",
                payload={"document_id": document.id, "reindex": True, "reason": "reindex"},
                progress=0.0,
                user_id=job.user_id,
                created_at=now,
            )
        )
        job.progress = round(index / max(1, len(documents)), 3)
        await session.flush()
    job.progress = 1.0
    job.state = "done"
    job.finished_at = utcnow()
    session.add(
        AuditLog(
            id=new_id("aud"),
            actor_id=job.user_id,
            actor_type="user" if job.user_id else "system",
            action="reindex_dispatched",
            object_type="job",
            object_id=job.id,
            detail={"documents": len(documents)},
            created_at=now,
        )
    )
    await session.commit()
    logger.info("reindex_dispatched", extra={"event": "reindex", "documents": len(documents)})
