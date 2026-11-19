"""Raw LightRAG retrieval without fact-checking (PROTOCOL §5.3).

This is deliberately not a second check: it calls stock LightRAG's retrieval endpoint
(``/query/data``), returns the matching passages and graph records, and never asks the
model for an answer.  Every returned source is resolved against the application database
first, so a chunk from a withdrawn document cannot reappear while LightRAG's asynchronous
deletion is still running.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.api import (
    RawRetrievalChunk,
    RawRetrievalDocument,
    RawRetrievalDocumentSummary,
    RawRetrievalMode,
    RawRetrievalResponse,
)
from app.db.models import Document, DocumentVersion
from app.retrieval.lightrag import LightRAGClient, RetrievalChunk
from app.services.source_refs import parse_source


@dataclass
class RawRetrievalService:
    session: AsyncSession
    lightrag: LightRAGClient

    async def retrieve(
        self,
        *,
        query: str,
        mode: RawRetrievalMode,
        top_k: int,
        chunk_top_k: int,
        include_graph: bool,
    ) -> RawRetrievalResponse:
        started = time.monotonic()
        result = await self.lightrag.query_data(
            query,
            mode=mode,
            top_k=top_k,
            chunk_top_k=chunk_top_k,
        )

        sources = {
            source
            for chunk in result.chunks
            if (source := parse_source(chunk.file_path)) is not None
        }
        if include_graph:
            for item in [*result.entities, *result.relationships]:
                file_path = item.get("file_path")
                source = parse_source(file_path if isinstance(file_path, str) else None)
                if source is not None:
                    sources.add(source)

        live = await self._live_documents(sources)
        grouped: dict[tuple[str, int], RawRetrievalDocument] = {}
        dropped_chunks = 0
        for chunk in result.chunks:
            source = parse_source(chunk.file_path)
            document = live.get(source) if source is not None else None
            if source is None or document is None:
                dropped_chunks += 1
                continue
            key = (document.id, source[1])
            entry = grouped.get(key)
            if entry is None:
                entry = RawRetrievalDocument(document=self._summary(document, source[1]))
                grouped[key] = entry
            entry.chunks.append(self._chunk(chunk))

        entities: list[dict[str, Any]] = []
        relationships: list[dict[str, Any]] = []
        dropped_entities = 0
        dropped_relationships = 0
        if include_graph:
            entities, dropped_entities = self._live_graph(result.entities, live)
            relationships, dropped_relationships = self._live_graph(result.relationships, live)

        return RawRetrievalResponse(
            query=query,
            mode=mode,
            top_k=top_k,
            chunk_top_k=chunk_top_k,
            documents=list(grouped.values()),
            entities=entities,
            relationships=relationships,
            returned_chunks=sum(len(item.chunks) for item in grouped.values()),
            dropped_chunks=dropped_chunks,
            returned_entities=len(entities),
            dropped_entities=dropped_entities,
            returned_relationships=len(relationships),
            dropped_relationships=dropped_relationships,
            took_ms=int((time.monotonic() - started) * 1000),
        )

    async def _live_documents(
        self, sources: set[tuple[str, int]]
    ) -> dict[tuple[str, int], Document]:
        if not sources:
            return {}
        rows = (
            await self.session.execute(
                select(DocumentVersion, Document)
                .join(Document, Document.id == DocumentVersion.document_id)
                .where(DocumentVersion.document_id.in_({source[0] for source in sources}))
            )
        ).all()
        live: dict[tuple[str, int], Document] = {}
        for version, document in rows:
            key = (document.id, version.version)
            if (
                key in sources
                and not document.deleted
                and document.state in {"approved", "indexed"}
            ):
                live[key] = document
        return live

    @staticmethod
    def _summary(document: Document, version: int) -> RawRetrievalDocumentSummary:
        return RawRetrievalDocumentSummary(
            id=document.id,
            version=version,
            title=document.title,
            publisher=document.publisher,
            publication_date=document.publication_date,
            source_quality=document.source_quality,
            language=document.language,
            url=document.url,
            license=document.license,
            redistribution=document.redistribution,
        )

    @staticmethod
    def _chunk(chunk: RetrievalChunk) -> RawRetrievalChunk:
        reference = chunk.raw.get("reference_id")
        return RawRetrievalChunk(
            chunk_id=chunk.chunk_id,
            reference_id=str(reference) if reference is not None else None,
            content=chunk.content,
            file_path=chunk.file_path,
            score=chunk.score,
            order=chunk.order,
        )

    @staticmethod
    def _live_graph(
        items: list[dict[str, Any]], live: dict[tuple[str, int], Document]
    ) -> tuple[list[dict[str, Any]], int]:
        kept: list[dict[str, Any]] = []
        dropped = 0
        for item in items:
            file_path = item.get("file_path")
            source = parse_source(file_path if isinstance(file_path, str) else None)
            if source is not None and source in live:
                kept.append(item)
            else:
                dropped += 1
        return kept, dropped
