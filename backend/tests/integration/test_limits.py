"""Per-user and per-key limits are enforced before work starts (IMPLEMENT Phase 5)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from app.core.ids import new_id, utcnow
from app.core.security import hash_password
from app.db.models import User
from app.services import checks as checks_service
from app.services.auth import create_api_key

from tests import fakes

pytestmark = pytest.mark.integration

CLAIM = "This claim is long enough to exceed a tiny text limit."


async def _user(app: Any, *, text_chars: int | None, requests_per_day: int | None) -> Any:
    async with app.state.db.session_factory() as session:
        user = User(
            id=new_id("usr"),
            email=f"limits-{new_id('x').lower()}@test.invalid",
            display_name="Limited",
            password_hash=hash_password("limits-password-77"),
            roles=["user"],
            permissions=[],
            denied_permissions=[],
            text_chars=text_chars,
            requests_per_day=requests_per_day,
            is_active=True,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        session.add(user)
        await session.commit()
        return user


@pytest.mark.asyncio
async def test_a_lower_api_key_limit_fails_while_the_owner_session_still_works(
    app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await _user(app, text_chars=1000, requests_per_day=50)
    async with app.state.db.session_factory() as session:
        _row, tight = await create_api_key(
            session, user=user, name="tight", limits={"text_chars": 10}
        )
        _row2, roomy = await create_api_key(session, user=user, name="roomy")
        await session.commit()
    monkeypatch.setattr(
        checks_service, "LLMClient", lambda settings, consumer="pipeline": fakes.FakeLLM()
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        tight_response = await client.post(
            "/v1/factcheck",
            json={"input": {"type": "text", "text": CLAIM}},
            headers={"Authorization": f"Bearer {tight}"},
        )
        assert tight_response.status_code == 413
        assert tight_response.json()["code"] == "payload_too_large"

        roomy_response = await client.post(
            "/v1/factcheck",
            json={"input": {"type": "text", "text": CLAIM}},
            headers={"Authorization": f"Bearer {roomy}"},
        )
        assert roomy_response.status_code == 202, roomy_response.text

        login = await client.post(
            "/api/auth/login",
            json={"email": user.email, "password": "limits-password-77"},
        )
        assert login.status_code == 200, login.text
        session_response = await client.post(
            "/v1/factcheck",
            json={"input": {"type": "text", "text": CLAIM}},
            headers={"X-CSRF-Token": login.json()["csrf_token"]},
        )
        assert session_response.status_code == 202, session_response.text


@pytest.mark.asyncio
async def test_the_daily_request_limit_is_enforced_before_the_second_job(
    app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await _user(app, text_chars=1000, requests_per_day=1)
    async with app.state.db.session_factory() as session:
        _row, token = await create_api_key(session, user=user, name="daily")
        await session.commit()
    monkeypatch.setattr(
        checks_service, "LLMClient", lambda settings, consumer="pipeline": fakes.FakeLLM()
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.post(
            "/v1/factcheck",
            json={"input": {"type": "text", "text": CLAIM}},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert first.status_code == 202, first.text
        second = await client.post(
            "/v1/factcheck",
            json={"input": {"type": "text", "text": CLAIM}},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert second.status_code == 429
        assert second.json()["code"] == "rate_limit_exceeded"


@pytest.mark.asyncio
async def test_user_administration_sets_and_validates_limits(
    client: httpx.AsyncClient,
) -> None:
    created = await client.post(
        "/v1/users",
        json={
            "email": "bounded@test.invalid",
            "display_name": "Bounded",
            "password": "quota-horse-battery-9",
            "roles": ["user"],
        },
    )
    assert created.status_code == 201, created.text
    user_id = created.json()["id"]
    patched = await client.patch(
        f"/v1/users/{user_id}",
        json={"requests_per_day": 3, "text_chars": 500},
    )
    assert patched.status_code == 200
    assert patched.json()["requests_per_day"] == 3
    assert patched.json()["text_chars"] == 500
    assert patched.json()["totp_enabled"] is False

    role_change = await client.patch(f"/v1/users/{user_id}", json={"roles": ["admin"]})
    assert role_change.status_code == 200
    assert role_change.json()["roles"] == ["admin"]

    bad_limit = await client.patch(f"/v1/users/{user_id}", json={"text_chars": 0})
    assert bad_limit.status_code == 422
    assert bad_limit.json()["code"] == "invalid_limit"
