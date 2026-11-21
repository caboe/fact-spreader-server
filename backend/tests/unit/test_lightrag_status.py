"""LightRAG track status: an index job waits for its own document, not the queue."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from app.retrieval.lightrag import LightRAGClient, LightRAGError
from pydantic import SecretStr


def _client(handler: Any) -> LightRAGClient:
    settings = SimpleNamespace(
        lightrag_base_url="http://lightrag.test",
        lightrag_api_key=SecretStr("test-key"),
        lightrag_timeout_seconds=1.0,
        lightrag_top_k=10,
        lightrag_chunk_top_k=5,
    )
    return LightRAGClient(settings, transport=httpx.MockTransport(handler))  # type: ignore[arg-type]


def _track(*statuses: str, error: str | None = None) -> dict[str, Any]:
    return {
        "track_id": "track-1",
        "documents": [
            {
                "id": f"doc-{index}",
                "status": status,
                "file_path": "doc_1@v1",
                "error_msg": error if status == "failed" else None,
            }
            for index, status in enumerate(statuses)
        ],
        "total_count": len(statuses),
    }


@pytest.mark.asyncio
async def test_an_insert_is_not_done_before_its_track_appears() -> None:
    """Prevents an index job from finishing in milliseconds while LightRAG still queues it.

    ``POST /documents/text`` schedules a background task; the track can be empty right
    after the response. The old global wait saw an empty document list and returned.
    """
    responses = iter([_track(), _track("processed")])
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json=next(responses))

    await _client(handler).wait_until_track_processed("track-1", timeout_seconds=1, interval=0.001)
    assert calls == ["/documents/track_status/track-1"] * 2


@pytest.mark.parametrize("state", ["pending", "parsing", "analyzing", "preprocessed", "processing"])
@pytest.mark.asyncio
async def test_every_state_before_processed_keeps_the_wait_open(state: str) -> None:
    """Prevents a job from marking a document indexed while LightRAG is still parsing it."""
    responses = iter([_track(state), _track("processed")])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=next(responses))

    await _client(handler).wait_until_track_processed("track-1", timeout_seconds=1, interval=0.001)


@pytest.mark.asyncio
async def test_a_processed_track_does_not_read_the_global_document_list() -> None:
    """Prevents one stale document from blocking a worker for another document."""
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(200, json=_track("processed"))

    await _client(handler).wait_until_track_processed("track-1", timeout_seconds=1, interval=0.001)
    assert paths == ["/documents/track_status/track-1"]


@pytest.mark.asyncio
async def test_a_failed_track_fails_the_wait_and_keeps_its_error() -> None:
    """Prevents a failed LightRAG document from being marked indexed."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_track("failed", error="extraction failed"))

    with pytest.raises(LightRAGError, match="extraction failed"):
        await _client(handler).wait_until_track_processed(
            "track-1", timeout_seconds=1, interval=0.001
        )


@pytest.mark.asyncio
async def test_a_track_that_never_appears_does_not_count_as_done() -> None:
    """A silently failed background enqueue must not mark the document indexed."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_track())

    with pytest.raises(LightRAGError, match="did not finish indexing"):
        await _client(handler).wait_until_track_processed(
            "track-1", file_source="doc_1@v1", timeout_seconds=0.01, interval=0.001
        )


@pytest.mark.asyncio
async def test_insert_text_returns_the_track_id_used_for_waiting() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/documents/text"
        return httpx.Response(200, json={"status": "success", "track_id": "track-abc"})

    assert await _client(handler).insert_text(content="body", file_source="doc_1@v1") == "track-abc"


@pytest.mark.asyncio
async def test_insert_text_requires_the_track_id_used_for_waiting() -> None:
    """Without a track id the caller cannot know which document to wait for."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "success"})

    with pytest.raises(LightRAGError, match="track id"):
        await _client(handler).insert_text(content="body", file_source="doc_1@v1")
