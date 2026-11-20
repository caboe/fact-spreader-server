"""Stock LightRAG HTTP client (PURPOSE §3.1, AGENTS.md invariant 7).

Only documented HTTP endpoints are used. Answer generation (``/query``,
``/query/stream``) is forbidden by construction: retrieval goes through
``POST /query/data`` and returns chunks, entities and relations, so the gate and the
citations stay in our code.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from app.core.config import Settings
from app.core.http import OutboundHTTP

FORBIDDEN_PATHS = ("/query", "/query/stream")


class LightRAGError(RuntimeError):
    pass


@dataclass(frozen=True)
class RetrievalChunk:
    content: str
    file_path: str | None
    chunk_id: str | None = None
    score: float | None = None
    order: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RetrievalResult:
    chunks: list[RetrievalChunk]
    entities: list[dict[str, Any]] = field(default_factory=list)
    relationships: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


class LightRAGClient:
    def __init__(self, settings: Settings, *, transport: Any = None) -> None:
        self._base = settings.lightrag_base_url.rstrip("/")
        self._key = settings.lightrag_api_key.get_secret_value()
        self._http = OutboundHTTP(
            timeout=settings.lightrag_timeout_seconds,
            retries=1,
            transport=transport,
        )
        self._top_k = settings.lightrag_top_k
        self._chunk_top_k = settings.lightrag_chunk_top_k
        self.calls: list[tuple[str, str]] = []

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._key:
            headers["X-API-Key"] = self._key
        return headers

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        if path in FORBIDDEN_PATHS or path.startswith("/query/stream"):
            raise LightRAGError(f"{path} is answer generation and is never called")
        self.calls.append((method.upper(), path))
        response = await self._http.request(
            method,
            f"{self._base}{path}",
            headers=self._headers(),
            **kwargs,
        )
        if response.status_code >= 400:
            raise LightRAGError(
                f"LightRAG {method} {path} returned HTTP {response.status_code}: "
                f"{response.text[:300]}"
            )
        if not response.content:
            return {}
        try:
            payload = response.json()
        except ValueError as exc:
            raise LightRAGError(f"LightRAG returned non-JSON for {path}") from exc
        if not isinstance(payload, dict):
            raise LightRAGError(f"LightRAG returned a non-object for {path}")
        return payload

    async def health(self) -> bool:
        try:
            payload = await self._request("GET", "/health")
        except Exception:
            return False
        return str(payload.get("status", "")).lower() in {"healthy", "ok", "up"} or bool(payload)

    async def insert_text(
        self,
        *,
        content: str,
        file_source: str,
        title: str | None = None,
    ) -> str | None:
        body: dict[str, Any] = {"text": content, "file_source": file_source}
        if title:
            body["description"] = title
        payload = await self._request("POST", "/documents/text", json=body)
        return payload.get("track_id") or payload.get("id")

    async def document_status(self) -> dict[str, Any]:
        return await self._request("GET", "/documents")

    async def delete_documents(self, doc_ids: list[str]) -> dict[str, Any]:
        return await self._request(
            "DELETE", "/documents/delete_document", json={"doc_ids": doc_ids}
        )

    async def delete_by_file_source(self, file_sources: list[str]) -> int:
        """Delete stored documents whose ``file_path`` is one of our ``doc@v`` sources.

        LightRAG's delete endpoint addresses its internal document id, not the file
        source; passing the source silently deletes nothing (it answers 200 with a
        warning). Resolve the ids first so a withdrawal or re-index really removes the
        old index entry.
        """
        wanted = set(file_sources)
        if not wanted:
            return 0
        payload = await self.document_status()
        statuses = payload.get("statuses") or {}
        ids: list[str] = []
        if isinstance(statuses, dict):
            for entries in statuses.values():
                for entry in entries or []:
                    if isinstance(entry, dict) and (
                        entry.get("file_path") in wanted or entry.get("id") in wanted
                    ):
                        ids.append(str(entry["id"]))
        if not ids:
            return 0
        await self.delete_documents(ids)
        return len(ids)

    async def wait_until_sources_absent(
        self, file_sources: list[str], *, timeout_seconds: float = 300.0
    ) -> bool:
        """Wait until LightRAG's asynchronous deletion no longer lists our sources.

        The delete endpoint returns before the clearing pipeline has finished; inserting
        the same file source in that window is rejected with a 409. Polling the document
        list closes that race without sleeping a fixed time.
        """
        wanted = set(file_sources)
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            payload = await self.document_status()
            statuses = payload.get("statuses") or {}
            present = False
            if isinstance(statuses, dict):
                for entries in statuses.values():
                    for entry in entries or []:
                        if isinstance(entry, dict) and entry.get("file_path") in wanted:
                            present = True
                            break
                    if present:
                        break
            if not present:
                return True
            await asyncio.sleep(0.5)
        return False

    async def query_data(
        self,
        query: str,
        *,
        high_level_keywords: list[str] | None = None,
        low_level_keywords: list[str] | None = None,
        top_k: int | None = None,
        chunk_top_k: int | None = None,
        mode: str = "mix",
    ) -> RetrievalResult:
        body: dict[str, Any] = {
            "query": query,
            "mode": mode,
            "top_k": top_k or self._top_k,
            "chunk_top_k": chunk_top_k or self._chunk_top_k,
            "only_need_context": True,
            "enable_rerank": False,
        }
        if high_level_keywords:
            body["hl_keywords"] = high_level_keywords
        if low_level_keywords:
            body["ll_keywords"] = low_level_keywords
        payload = await self._request("POST", "/query/data", json=body)
        return _parse_retrieval(payload)

    async def wait_until_idle(
        self, *, timeout_seconds: float = 900.0, interval: float = 3.0
    ) -> bool:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            status = await self.document_status()
            if not _has_unfinished_documents(status):
                return True
            await asyncio.sleep(interval)
        return False


def _parse_retrieval(payload: dict[str, Any]) -> RetrievalResult:
    nested = payload.get("data")
    data: dict[str, Any] = nested if isinstance(nested, dict) else payload
    chunks: list[RetrievalChunk] = []
    for position, item in enumerate(data.get("chunks") or []):
        if isinstance(item, str):
            if item.strip():
                chunks.append(RetrievalChunk(content=item, file_path=None, order=position))
            continue
        if not isinstance(item, dict):
            continue
        content = item.get("content") or item.get("text") or ""
        if not isinstance(content, str) or not content.strip():
            continue
        chunks.append(
            RetrievalChunk(
                content=content,
                file_path=item.get("file_path") or item.get("file_source"),
                chunk_id=item.get("chunk_id") or item.get("id"),
                score=_as_float(item.get("score") or item.get("similarity")),
                order=item.get("chunk_order_index")
                if isinstance(item.get("chunk_order_index"), int)
                else position,
                raw=item,
            )
        )
    return RetrievalResult(
        chunks=chunks,
        entities=[item for item in (data.get("entities") or []) if isinstance(item, dict)],
        relationships=[
            item for item in (data.get("relationships") or []) if isinstance(item, dict)
        ],
        raw=payload,
    )


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# LightRAG v1.5.0 runs PENDING -> PARSING -> ANALYZING -> PROCESSING -> PROCESSED | FAILED
# (``lightrag.base.DocStatus``; PREPROCESSED is its deprecated name for ANALYZING). Every
# state before a final one is unfinished: treating only pending/processing as busy let
# seed-fixtures report "ready" while 21 of 23 documents were still being parsed.
_UNFINISHED_STATES = ("pending", "parsing", "analyzing", "preprocessed", "processing")


def _has_unfinished_documents(status: dict[str, Any]) -> bool:
    statuses = status.get("statuses")
    if isinstance(statuses, dict):
        for key in _UNFINISHED_STATES:
            value = statuses.get(key)
            if isinstance(value, list) and value:
                return True
            if isinstance(value, int) and value > 0:
                return True
    for key in _UNFINISHED_STATES:
        value = status.get(key)
        if isinstance(value, list) and value:
            return True
    return False
