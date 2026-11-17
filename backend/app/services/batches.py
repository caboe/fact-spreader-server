"""Batch document upload helpers (PROTOCOL §8.7).

A batch is a bracket around independent documents. ZIP entries are inspected before any
parse: absolute paths, parent traversal, symlinks and oversized entries are skipped while
safe entries continue. Failed entries remain visible as documents in state ``failed``.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import mimetypes
import zipfile
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.api import (
    BatchCounts,
    BatchFile,
    BatchInfo,
    DocumentMetadata,
    DocumentWarning,
)
from app.core.config import Settings
from app.core.ids import new_id, sha256_text, utcnow
from app.db.models import Document, DocumentBatch, DocumentVersion
from app.services.documents import document_to_api, latest_version

logger = logging.getLogger(__name__)

MAX_FILES = 100
MAX_TOTAL_BYTES = 200_000_000


def sanitise_zip(data: bytes, settings: Settings) -> tuple[list[tuple[str, bytes, str]], list[str]]:
    files: list[tuple[str, bytes, str]] = []
    warnings: list[str] = []
    total = 0
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return [], ["zip_sanitized: the archive is not a valid ZIP file"]
    with archive:
        for info in archive.infolist():
            name = info.filename
            if info.is_dir():
                continue
            if name.startswith("/") or ".." in name.split("/") or "\\" in name:
                warnings.append(f"zip_sanitized: skipped unsafe path {name!r}")
                continue
            mode = (info.external_attr >> 16) & 0o170000
            if mode == 0o120000:
                warnings.append(f"zip_sanitized: skipped symlink {name!r}")
                continue
            if info.file_size > settings.upload_max_bytes:
                warnings.append(f"zip_sanitized: skipped oversized entry {name!r}")
                continue
            total += info.file_size
            if total > MAX_TOTAL_BYTES or len(files) >= MAX_FILES:
                warnings.append("zip_sanitized: archive limits exceeded; remaining entries skipped")
                break
            try:
                payload = archive.read(info)
            except (RuntimeError, zipfile.BadZipFile):
                warnings.append(f"zip_sanitized: could not read {name!r}")
                continue
            media = mimetypes.guess_type(name)[0] or "application/octet-stream"
            files.append((name.rsplit("/", 1)[-1], payload, media))
    return files, warnings


async def create_batch(session: AsyncSession, *, user_id: str | None) -> DocumentBatch:
    now = utcnow()
    batch = DocumentBatch(
        id=new_id("bch"),
        state="processing",
        counts={},
        estimated_usd="0",
        submitted_by=user_id,
        created_at=now,
        updated_at=now,
    )
    session.add(batch)
    await session.flush()
    return batch


async def record_failure(
    session: AsyncSession,
    *,
    batch: DocumentBatch,
    filename: str,
    reason: str,
    user_id: str | None,
    raw_bytes: bytes | None = None,
    raw_media_type: str | None = None,
) -> Document:
    now = utcnow()
    document = Document(
        id=new_id("doc"),
        title=filename[:500],
        publisher="Unknown",
        authors=[],
        publication_date=None,
        url=None,
        doi=None,
        dataset_id=None,
        source_quality="D",
        source_quality_basis={"source": "default_unknown"},
        domain_tags=[],
        language="en",
        license=None,
        redistribution="metadata_only",
        origin_instance_id="",
        origin_document_id="",
        content_hash=sha256_text(filename + reason),
        state="failed",
        version=1,
        content_type="text/plain",
        warnings=[{"code": "parse_warning", "message": reason[:500]}],
        figures=[],
        batch_id=batch.id,
        submitted_by=user_id,
        deleted=False,
        created_at=now,
        updated_at=now,
    )
    document.origin_instance_id = document.id
    document.origin_document_id = document.id
    version = DocumentVersion(
        id=new_id("ver"),
        document_id=document.id,
        version=1,
        content_hash=document.content_hash,
        content_md="",
        file_path=filename,
        raw_bytes=raw_bytes,
        raw_media_type=raw_media_type,
        size_bytes=0,
        created_at=now,
    )
    session.add_all([document, version])
    await session.flush()
    return document


async def batch_counts(session: AsyncSession, batch_id: str) -> BatchCounts:
    rows = (
        (
            await session.execute(
                select(Document.state).where(
                    Document.batch_id == batch_id, Document.deleted.is_(False)
                )
            )
        )
        .scalars()
        .all()
    )
    return BatchCounts(
        total=len(rows),
        ready=sum(1 for state in rows if state in {"ready", "parsed"}),
        warning=sum(1 for state in rows if state == "warning"),
        duplicate=sum(1 for state in rows if state == "duplicate"),
        failed=sum(1 for state in rows if state == "failed"),
    )


async def batch_to_api(
    session: AsyncSession,
    batch: DocumentBatch,
    *,
    budget_remaining: float | None = None,
    warnings: list[str] | None = None,
) -> BatchInfo:
    documents = (
        (
            await session.execute(
                select(Document)
                .where(Document.batch_id == batch.id, Document.deleted.is_(False))
                .order_by(Document.created_at)
            )
        )
        .scalars()
        .all()
    )
    files: list[BatchFile] = []
    for document in documents:
        version = await latest_version(session, document)
        info = document_to_api(document, version=version, show_identity=True)
        files.append(
            BatchFile(
                document_id=document.id,
                filename=(version.file_path if version and version.file_path else document.title),
                state=document.state,
                warnings=info.warnings,
            )
        )
    counts = await batch_counts(session, batch.id)
    return BatchInfo(
        id=batch.id,
        state=batch.state,
        counts=counts,
        estimated_usd=float(batch.estimated_usd or 0),
        budget_remaining_usd=budget_remaining,
        files=files,
        warnings=[DocumentWarning(code="zip_sanitized", message=item) for item in (warnings or [])],
        created_at=batch.created_at,
        updated_at=batch.updated_at,
    )


async def finalise_batch(session: AsyncSession, batch: DocumentBatch) -> None:
    counts = await batch_counts(session, batch.id)
    batch.counts = counts.model_dump(mode="json")
    batch.state = "ready" if counts.failed == 0 else "partial"
    batch.updated_at = utcnow()


def parse_metadata_sidecar(data: bytes, filename: str) -> dict[str, DocumentMetadata]:
    """Parse a JSON or CSV sidecar keyed by uploaded filename.

    Unknown or malformed rows are skipped; the batch still processes the files.
    """
    text = data.decode("utf-8", errors="replace")
    result: dict[str, DocumentMetadata] = {}
    try:
        if filename.lower().endswith(".json") or text.lstrip().startswith("{"):
            raw = json.loads(text)
            if not isinstance(raw, dict):
                return {}
            for key, value in raw.items():
                if isinstance(value, dict):
                    result[str(key)] = DocumentMetadata.model_validate(value)
            return result
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            name = str(row.get("filename") or row.get("file") or "").strip()
            if not name:
                continue
            payload: dict[str, Any] = {}
            for field in (
                "title",
                "publisher",
                "publication_date",
                "url",
                "doi",
                "dataset_id",
                "license",
                "redistribution",
                "language",
                "source_quality_override",
            ):
                value = (row.get(field) or "").strip()
                if value:
                    payload[field] = value
            for field in ("authors", "domain_tags"):
                value = (row.get(field) or "").strip()
                if value:
                    payload[field] = [
                        item.strip() for item in value.replace("|", ";").split(";") if item.strip()
                    ]
            result[name] = DocumentMetadata.model_validate(payload)
    except (ValueError, TypeError, json.JSONDecodeError):
        logger.warning("batch_metadata_sidecar_invalid")
    return result
