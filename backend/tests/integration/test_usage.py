"""Usage summaries and CSV contain quantities that match the recorded events."""

from __future__ import annotations

import csv
import io
from datetime import timedelta
from typing import Any

import httpx
import pytest
from app.core.ids import new_id, utcnow
from app.db.models import UsageEvent

pytestmark = pytest.mark.integration


def _event(
    *, consumer: str, role: str, tokens_in: int, tokens_out: int, cost: str, when: Any
) -> UsageEvent:
    return UsageEvent(
        id=new_id("use"),
        request_id=None,
        user_id=None,
        api_key_id=None,
        consumer=consumer,
        role=role,
        provider="deepseek",
        model="deepseek-flash",
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=cost,
        cost_estimated=False,
        latency_ms=10,
        status=200,
        data_classes=[],
        created_at=when,
    )


@pytest.mark.asyncio
async def test_usage_summary_and_csv_match_the_recorded_events(
    client: httpx.AsyncClient, app: Any
) -> None:
    when = utcnow() - timedelta(days=2)
    async with app.state.db.session_factory() as session:
        session.add_all(
            [
                _event(
                    consumer="pipeline",
                    role="fs-verify",
                    tokens_in=100,
                    tokens_out=10,
                    cost="0.001000",
                    when=when,
                ),
                _event(
                    consumer="pipeline",
                    role="fs-extract",
                    tokens_in=100,
                    tokens_out=10,
                    cost="0.001000",
                    when=when,
                ),
                _event(
                    consumer="research",
                    role="fs-chat",
                    tokens_in=50,
                    tokens_out=5,
                    cost="0.000500",
                    when=when,
                ),
            ]
        )
        await session.commit()

    params = {"from": when.date().isoformat(), "to": when.date().isoformat()}
    summary = await client.get("/v1/usage/summary", params=params)
    assert summary.status_code == 200, summary.text
    body = summary.json()
    assert body["totals"] == {
        "calls": 3,
        "tokens_in": 250,
        "tokens_out": 25,
        "cost_usd": pytest.approx(0.0025),
    }
    consumers = {row["key"]: row for row in body["breakdowns"]["consumer"]}
    assert consumers["pipeline"]["calls"] == 2
    assert consumers["research"]["calls"] == 1
    assert body["series"][0]["calls"] == 3

    csv_response = await client.get("/v1/usage/summary.csv", params=params)
    assert csv_response.status_code == 200
    assert csv_response.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(csv_response.text)))
    assert {row["consumer"] for row in rows} == {"pipeline", "research"}
    assert sum(int(row["calls"]) for row in rows) == 3
    assert sum(int(row["tokens_in"]) for row in rows) == 250
    assert sum(float(row["cost_usd"]) for row in rows) == pytest.approx(0.0025)
    assert "text" not in csv_response.text
