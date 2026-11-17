"""Document submission, review and indexing (PROTOCOL §8).

Content is untrusted data. Submission stores a parsed Markdown version and warnings;
approval is the only path into LightRAG. Indexing runs in the worker with
``file_source = <doc_id>@v<version>`` so stored evidence keeps a resolvable provenance.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.api import (
    DocumentApproval,
    DocumentEstimate,
    DocumentFigure,
    DocumentInfo,
    DocumentMetadata,
    DocumentWarning,
)
from app.contracts.enums import TurnType
from app.core.config import Settings
from app.core.ids import new_id, sha256_text, utcnow
from app.db.models import Document, DocumentVersion, Instance, Result
from app.db.models import Job as JobRow
from app.retrieval.lightrag import LightRAGClient, LightRAGError
from app.services.checks import create_check_job
from app.services.methodology import Methodology
from app.services.publishers import PublisherRegistry

logger = logging.getLogger(__name__)

_INJECTION = re.compile(
    r"(ignore (all )?(previous|prior|above) instructions|system prompt|"
    r"you are now|developer message|jailbreak|do not follow the rules)",
    re.IGNORECASE,
)


def _warnings(
    *,
    content: str,
    language: str,
    supported: list[str],
    license_: str | None,
    quality: str,
    duplicate_of: str | None,
) -> list[DocumentWarning]:
    warnings: list[DocumentWarning] = []
    if duplicate_of:
        warnings.append(
            DocumentWarning(
                code="duplicate_suspected",
                message=f"A near-duplicate of {duplicate_of} exists.",
            )
        )
    if language not in supported:
        warnings.append(
            DocumentWarning(
                code="unsupported_language",
                message=f"The document language {language!r} is not supported.",
            )
        )
    if not license_:
        warnings.append(
            DocumentWarning(
                code="license_missing",
                message="No license is recorded; the editor must confirm the metadata.",
            )
        )
    if quality == "D":
        warnings.append(
            DocumentWarning(
                code="low_source_grade",
                message="The publisher resolves to source grade D.",
            )
        )
    if _INJECTION.search(content):
        warnings.append(
            DocumentWarning(
                code="injection_suspected",
                message="The document contains text that looks like an instruction.",
            )
        )
    return warnings


def document_to_api(
    document: Document,
    *,
    version: DocumentVersion | None,
    show_identity: bool,
    warnings: list[DocumentWarning] | None = None,
) -> DocumentInfo:
    approval = None
    if document.approved_at and document.approved_by:
        approval = DocumentApproval(
            approved_at=document.approved_at,
            approved_by=document.approved_by if show_identity else "usr_redacted",
            note=document.notes,
        )
    figures = [
        DocumentFigure.model_validate(item)
        for item in (document.figures or [])
        if isinstance(item, dict)
    ]
    return DocumentInfo(
        id=document.id,
        version=document.version,
        content_hash=document.content_hash,
        title=document.title,
        publisher=document.publisher,
        authors=list(document.authors or []),
        publication_date=document.publication_date,
        url=document.url,
        doi=document.doi,
        dataset_id=document.dataset_id,
        source_quality=document.source_quality,
        source_quality_basis=dict(document.source_quality_basis or {}),
        domain_tags=list(document.domain_tags or []),
        language=document.language,
        license=document.license,
        redistribution=document.redistribution,
        curator_organization=document.curator_organization,
        origin_instance_id=document.origin_instance_id,
        origin_document_id=document.origin_document_id,
        provenance_chain=(
            [{"instance_id": document.origin_instance_id, "approved_at": document.approved_at}]
            if document.approved_at
            else []
        ),
        content_type=document.content_type,
        size_bytes=version.size_bytes if version else 0,
        state=document.state,
        warnings=warnings
        if warnings is not None
        else [
            DocumentWarning.model_validate(item)
            for item in (document.warnings or [])
            if isinstance(item, dict)
        ],
        duplicate_of=document.duplicate_of,
        submitted_by=document.submitted_by if show_identity else None,
        approval=approval,
        figures=figures,
        approval_preselected=document.state in {"ready", "parsed"} and not document.warnings,
        created_at=document.created_at,
        updated_at=document.updated_at,
        deleted=document.deleted,
    )


async def latest_version(session: AsyncSession, document: Document) -> DocumentVersion | None:
    return (
        await session.execute(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document.id)
            .order_by(DocumentVersion.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


def _estimate(content: str) -> DocumentEstimate:
    pages = max(1, len(content) // 3000 + 1)
    figures = content.count("![") + content.count("<img")
    return DocumentEstimate(
        pages=pages, figures=figures, vision_calls=0, estimated_usd=0.0, exceeds_budget=False
    )


async def create_document(
    session: AsyncSession,
    *,
    settings: Settings,
    publishers: PublisherRegistry,
    instance: Instance,
    user_id: str | None,
    content: str,
    content_type: str,
    size_bytes: int,
    metadata: DocumentMetadata,
    detected_language: str,
    unsupported_language: bool,
    source_url: str | None,
    figures: list[dict[str, Any]] | None = None,
    force: bool = False,
    batch_id: str | None = None,
) -> tuple[Document, DocumentVersion, list[DocumentWarning], str | None, DocumentEstimate]:
    content = content.strip()
    if not content:
        raise ValueError("empty document")
    content_hash = sha256_text(content)
    existing = (
        await session.execute(
            select(Document)
            .where(Document.content_hash == content_hash, Document.deleted.is_(False))
            .order_by(Document.created_at)
            .limit(1)
        )
    ).scalar_one_or_none()
    duplicate_of = None
    if existing is not None and not force:
        duplicate_of = existing.id
    publisher = (
        metadata.publisher or existing.publisher if existing else metadata.publisher
    ) or "Unknown"
    url = metadata.url or source_url or (existing.url if existing else None)
    doi = metadata.doi or (existing.doi if existing else None)
    quality = publishers.resolve(publisher=publisher, url=url, doi=doi)
    if metadata.source_quality_override:
        quality_grade = metadata.source_quality_override.upper()
        basis = {"source": "document_override", "entry": "submission"}
    else:
        quality_grade = quality.grade
        basis = quality.basis.model_dump(mode="json")
    language = metadata.language or detected_language
    warnings = _warnings(
        content=content,
        language=language,
        supported=settings.supported_languages,
        license_=metadata.license,
        quality=quality_grade,
        duplicate_of=duplicate_of,
    )
    now = utcnow()
    document_id = new_id("doc")
    document = Document(
        id=document_id,
        title=(metadata.title or "Untitled document")[:500],
        publisher=publisher[:300],
        authors=list(metadata.authors or []),
        publication_date=metadata.publication_date,
        url=url,
        doi=doi,
        dataset_id=metadata.dataset_id,
        source_quality=quality_grade,
        source_quality_basis=basis,
        domain_tags=list(metadata.domain_tags or []),
        language=language,
        license=metadata.license,
        redistribution=metadata.redistribution or "metadata_only",
        curator_organization=instance.organization,
        origin_instance_id=instance.id,
        origin_document_id=document_id,
        content_hash=content_hash,
        state="duplicate" if duplicate_of else ("warning" if warnings else "ready"),
        version=1,
        content_type=content_type,
        warnings=[item.model_dump(mode="json") for item in warnings],
        figures=figures or [],
        duplicate_of=duplicate_of,
        batch_id=batch_id,
        submitted_by=user_id,
        deleted=False,
        created_at=now,
        updated_at=now,
    )
    version = DocumentVersion(
        id=new_id("ver"),
        document_id=document_id,
        version=1,
        content_hash=content_hash,
        content_md=content,
        file_path=None,
        size_bytes=size_bytes,
        created_at=now,
    )
    session.add_all([document, version])
    await session.flush()
    return document, version, warnings, duplicate_of, _estimate(content)


async def update_corpus_version(session: AsyncSession, instance: Instance) -> None:
    docs = (
        await session.execute(
            select(Document.id, Document.version, Document.content_hash).where(
                Document.deleted.is_(False), Document.state == "indexed"
            )
        )
    ).all()
    payload = json.dumps(sorted([list(row) for row in docs]), sort_keys=True)
    instance.corpus_version = "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()
    instance.updated_at = utcnow()


async def run_document_index_job(
    session: AsyncSession,
    *,
    settings: Settings,
    lightrag: LightRAGClient,
    job: JobRow,
) -> None:
    payload = job.payload or {}
    document = await session.get(Document, str(payload.get("document_id") or ""))
    if document is None:
        raise ValueError("document_missing")
    version = await latest_version(session, document)
    if version is None:
        raise ValueError("document_version_missing")
    document.state = "indexing"
    document.updated_at = utcnow()
    await session.commit()
    file_source = f"{document.id}@v{document.version}"
    await lightrag.insert_text(
        content=version.content_md, file_source=file_source, title=document.title
    )
    if not await lightrag.wait_until_idle(timeout_seconds=900):
        raise LightRAGError("LightRAG did not finish indexing the document")
    document.state = "indexed"
    document.updated_at = utcnow()
    instance = (await session.execute(select(Instance).limit(1))).scalar_one_or_none()
    if instance is not None:
        await update_corpus_version(session, instance)
    publishers = PublisherRegistry.from_path(settings.publisher_list_path)
    methodology = Methodology.load(settings.checklist_dir, settings.pattern_list_path)
    summary = await enqueue_rechecks_for_document(
        session,
        settings=settings,
        publishers=publishers,
        methodology=methodology,
        document=document,
        reason="corpus_changed",
    )
    _record_recheck_summary(document, summary)
    logger.info(
        "document_rechecks_enqueued",
        extra={
            "event": "document",
            "enqueued": summary["enqueued"],
            "skipped": summary["skipped_budget"],
        },
    )
    await session.commit()
    logger.info("document_indexed", extra={"event": "document", "document_id": document.id})


async def queue_review_counts(session: AsyncSession) -> dict[str, int]:
    rows = (
        await session.execute(
            select(Document.state, func.count(Document.id))
            .where(Document.deleted.is_(False))
            .group_by(Document.state)
        )
    ).all()
    counts = {str(state): int(count) for state, count in rows}
    return {
        "ready": counts.get("ready", 0) + counts.get("parsed", 0),
        "warnings": counts.get("warning", 0),
        "duplicates": counts.get("duplicate", 0),
        "failed": counts.get("failed", 0),
        "approved": counts.get("approved", 0),
        "indexing": counts.get("indexing", 0),
        "indexed": counts.get("indexed", 0),
        "rejected": counts.get("rejected", 0),
        "withdrawn": counts.get("withdrawn", 0),
    }


def _record_recheck_summary(document: Document, summary: dict[str, int]) -> None:
    if not summary.get("skipped_budget"):
        return
    warnings = [dict(item) for item in (document.warnings or []) if isinstance(item, dict)]
    warnings = [item for item in warnings if item.get("code") != "budget_low"]
    warnings.append(
        {
            "code": "budget_low",
            "message": (
                f"{summary['skipped_budget']} affected claim(s) were not re-checked: the "
                "daily re-check budget is exhausted."
            ),
        }
    )
    document.warnings = warnings


async def enqueue_rechecks_for_document(
    session: AsyncSession,
    *,
    settings: Settings,
    publishers: PublisherRegistry,
    methodology: Methodology,
    document: Document,
    reason: str,
) -> dict[str, int]:
    """Queue re-checks for claims affected by an approval or withdrawal.

    Approval matches statements by domain tag; withdrawal matches results whose evidence
    references the document. The daily re-check budget is a hard cap; the return value
    reports how many were skipped for the editor instead of dropping them silently.
    """
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    used = int(
        (
            await session.execute(
                select(func.count(JobRow.id)).where(
                    JobRow.created_at >= today,
                    JobRow.payload["recheck"].astext == "true",
                )
            )
        ).scalar_one()
    )
    remaining = max(0, settings.recheck_daily_budget - used)
    candidates = (
        (
            await session.execute(
                select(Result)
                .where(
                    Result.deleted.is_(False),
                    Result.status == "complete",
                    Result.preliminary.is_(False),
                )
                .order_by(Result.created_at.desc())
                .limit(200)
            )
        )
        .scalars()
        .all()
    )
    claim_texts: set[str] = set()
    enqueued = 0
    skipped = 0
    for row in candidates:
        if reason == "withdrawal":
            related = any(
                str((item.get("provenance") or {}).get("document_id")) == document.id
                for item in (row.evidence or [])
                if isinstance(item, dict)
            )
        else:
            related = any(
                set(statement.get("domain_tags") or []) & set(document.domain_tags or [])
                for statement in (row.statements or [])
                if isinstance(statement, dict)
            )
        if not related:
            continue
        text = str((row.input or {}).get("text") or "").strip()
        normalized = text.casefold()
        if not text or normalized in claim_texts:
            continue
        claim_texts.add(normalized)
        if enqueued >= remaining:
            skipped += 1
            continue
        await create_check_job(
            session,
            settings=settings,
            publishers=publishers,
            methodology=methodology,
            text=text,
            user_id=row.user_id,
            response_language=row.response_language,
            turn_type=TurnType(row.turn_type),
            source_url=(row.input or {}).get("url"),
            source_file_name=(row.input or {}).get("file_name"),
            source_media_type=(row.input or {}).get("media_type"),
            source_size_bytes=(row.input or {}).get("size_bytes"),
            context=((row.input or {}).get("context") or {}).get("messages"),
            previous_result_id=row.id,
        )
        job = (
            await session.execute(select(JobRow).order_by(JobRow.created_at.desc()).limit(1))
        ).scalar_one()
        job.payload = {
            **(job.payload or {}),
            "recheck": True,
            "recheck_reason": reason,
            "recheck_document_id": document.id,
        }
        enqueued += 1
    return {"enqueued": enqueued, "skipped_budget": skipped}
