"""Budgets: paid calls stop at the monthly ceiling, free embeddings still serve cache."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, ClassVar

import httpx
import pytest
from app.api.internal import llm as gateway
from app.db.models import Instance
from sqlalchemy import select

pytestmark = pytest.mark.integration


class _FreeTransport:
    calls: ClassVar[list[str]] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def request(
        self,
        method: str,
        url: str,
        *,
        json: Any = None,
        headers: dict[str, str] | None = None,
        request_timeout: float | None = None,
    ) -> httpx.Response:
        _FreeTransport.calls.append(url)
        if url.endswith("/embeddings"):
            return httpx.Response(200, json={"data": [{"embedding": [0.1] * 1024}]})
        return httpx.Response(
            200,
            json={
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )


@pytest.mark.asyncio
async def test_exhausted_budget_returns_429_but_zero_cost_embeddings_still_run(
    app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with app.state.db.session_factory() as session:
        instance = (await session.execute(select(Instance).limit(1))).scalar_one()
        instance.monthly_budget_usd = Decimal("0.000000")
        await session.commit()
    monkeypatch.setattr(gateway, "OutboundHTTP", _FreeTransport)
    headers = {
        "Authorization": f"Bearer {app.state.settings.internal_llm_key.get_secret_value()}",
        "X-FS-Consumer": "pipeline",
        "X-FS-Data-Classes": "user_input",
        "X-FS-Purpose": "query",
    }
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as internal:
        _FreeTransport.calls = []
        paid = await internal.post(
            "/internal/llm/v1/chat/completions",
            headers=headers,
            json={"model": "fs-chat", "messages": [{"role": "user", "content": "hello"}]},
        )
        assert paid.status_code == 429, paid.text
        assert paid.json()["error"]["code"] == "budget_exceeded"
        assert "Retry-After" in paid.headers
        assert _FreeTransport.calls == []

        # The semantic cache embeds the claim with the local, zero-cost model. That must
        # keep working when the paid budget is exhausted, or cache hits would disappear.
        embedding_headers = {**headers, "X-FS-Purpose": "semantic_cache"}
        free = await internal.post(
            "/internal/llm/v1/embeddings",
            headers=embedding_headers,
            json={"model": "fs-embedding", "input": "hello"},
        )
        assert free.status_code == 200, free.text
        assert _FreeTransport.calls and _FreeTransport.calls[0].endswith("/embeddings")
    async with app.state.db.session_factory() as session:
        instance = (await session.execute(select(Instance).limit(1))).scalar_one()
        instance.monthly_budget_usd = Decimal("15.000000")
        await session.commit()
