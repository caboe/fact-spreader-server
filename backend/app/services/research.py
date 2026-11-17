"""Retrieval-only research mode (PROTOCOL §5, PURPOSE §3.2).

Documents and passages come from the existing approved LightRAG corpus; archive hits come
from checked claims. There is no verdict and no synthesis: the optional summary is not yet
implemented and is reported as unavailable rather than fabricated.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.api import (
    ResearchClaim,
    ResearchDocument,
    ResearchDocumentSummary,
    ResearchFilters,
    ResearchPassage,
    ResearchResponse,
    WarningInfo,
)
from app.contracts.enums import Verdict
from app.core.ids import new_id
from app.db.models import Document, DocumentVersion, Result
from app.retrieval.lightrag import LightRAGClient, RetrievalChunk
from app.services.publishers import grade_at_least

_FILE_SOURCE_RE = re.compile(r"(doc_[A-Za-z0-9]+)@v(\d+)")


@dataclass
class ResearchService:
    session: AsyncSession
    lightrag: LightRAGClient

    async def search(
        self,
        *,
        query: str,
        response_language: str,
        filters: ResearchFilters,
        summary: bool,
        limit: int,
    ) -> ResearchResponse:
        started = time.monotonic()
        result = await self.lightrag.query_data(query, top_k=40, chunk_top_k=25)
        grouped: dict[str, ResearchDocument] = {}
        for chunk in result.chunks[: limit * 4]:
            document = await self._document_for_chunk(chunk)
            if document is None:
                continue
            doc, _version = document
            if not self._matches(doc, filters):
                continue
            key = doc.id
            if key not in grouped:
                grouped[key] = ResearchDocument(
                    document=ResearchDocumentSummary(
                        id=doc.id,
                        title=doc.title,
                        publisher=doc.publisher,
                        publication_date=doc.publication_date,
                        source_quality=doc.source_quality,
                        language=doc.language,
                        url=doc.url,
                        license=doc.license,
                        redistribution=doc.redistribution,
                    )
                )
            grouped[key].passages.append(
                ResearchPassage(
                    evidence_id=new_id("psg"),
                    passage=chunk.content,
                    passage_language=doc.language,
                    locator=f"chunk {chunk.order}" if chunk.order is not None else None,
                    score=max(0.0, min(1.0, chunk.score or 0.5)),
                )
            )
        documents = sorted(
            grouped.values(),
            key=lambda item: max((p.score for p in item.passages), default=0.0),
            reverse=True,
        )[:limit]
        claims = await self._claims(query, filters)
        warnings: list[WarningInfo] = []
        if summary:
            warnings.append(
                WarningInfo(
                    code="summary_not_available",
                    message=(
                        "The cited research summary is not implemented yet; showing the "
                        "retrieval lists only."
                    ),
                )
            )
        return ResearchResponse(
            query=query,
            detected_language=response_language,
            response_language=response_language,
            documents=documents,
            claims=claims,
            warnings=warnings,
            took_ms=int((time.monotonic() - started) * 1000),
        )

    async def _document_for_chunk(
        self, chunk: RetrievalChunk
    ) -> tuple[Document, DocumentVersion] | None:
        match = _FILE_SOURCE_RE.search(chunk.file_path or "")
        if match is None:
            return None
        row = (
            await self.session.execute(
                select(DocumentVersion, Document)
                .join(Document, Document.id == DocumentVersion.document_id)
                .where(
                    DocumentVersion.document_id == match.group(1),
                    DocumentVersion.version == int(match.group(2)),
                )
            )
        ).first()
        if row is None:
            return None
        version, document = row
        if document.deleted or document.state not in {"approved", "indexed"}:
            return None
        return document, version

    @staticmethod
    def _matches(document: Document, filters: ResearchFilters) -> bool:
        if filters.domains and not set(filters.domains) & set(document.domain_tags or []):
            return False
        if filters.languages and document.language not in filters.languages:
            return False
        if (
            filters.start
            and document.publication_date
            and document.publication_date < filters.start
        ):
            return False
        if filters.end and document.publication_date and document.publication_date > filters.end:
            return False
        if filters.min_source_quality:
            return grade_at_least(document.source_quality, filters.min_source_quality)
        return True

    async def _claims(self, query: str, filters: ResearchFilters) -> list[ResearchClaim]:
        words = [word for word in re.findall(r"[^\W\d_]{4,}", query)][:3]
        if not words:
            return []
        clauses = [Result.input["text"].astext.ilike(f"%{word}%") for word in words]
        rows = (
            (
                await self.session.execute(
                    select(Result)
                    .where(Result.deleted.is_(False), or_(*clauses))
                    .order_by(Result.created_at.desc())
                    .limit(5)
                )
            )
            .scalars()
            .all()
        )
        claims: list[ResearchClaim] = []
        for row in rows:
            text = str((row.input or {}).get("text", ""))
            claims.append(
                ResearchClaim(
                    result_id=row.id,
                    claim_text=text[:500],
                    verdict=Verdict(row.overall_verdict) if row.overall_verdict else None,
                    created_at=row.created_at,
                    excerpt=text[:300],
                )
            )
        return claims
