"""First-run setup wizard: token, order, gate, TOTP and completion (IMPLEMENT Phase 5)."""

from __future__ import annotations

from typing import Any

import httpx
import pyotp
import pytest
from app.contracts.api import ModerationInfo
from app.core.errors import AppError
from app.db.models import ApiKey, DeviceToken, Instance, SessionToken, Setting, User
from app.services.setup import setup_gate
from pydantic import SecretStr
from sqlalchemy import delete

pytestmark = pytest.mark.integration

ADMIN_EMAIL = "setup@test.invalid"
ADMIN_PASSWORD = "correct-horse-battery-9"
SETUP_TOKEN = "test-setup-token"


async def _empty_database(app: Any) -> None:
    async with app.state.db.session_factory() as session:
        for model in (SessionToken, ApiKey, DeviceToken, User, Instance, Setting):
            await session.execute(delete(model))
        await session.commit()


async def _login(client: httpx.AsyncClient, email: str, password: str, code: str | None) -> Any:
    payload = {"email": email, "password": password}
    if code is not None:
        payload["totp_code"] = code
    return await client.post("/api/auth/login", json=payload)


@pytest.mark.asyncio
async def test_fresh_instance_completes_the_wizard_in_order_and_blocks_checks(
    app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _empty_database(app)

    async def fake_probe(base_url: str, api_key: str | None) -> list[str]:
        return ["deepseek-chat", "bge-m3"]

    async def fake_moderation(settings: Any) -> ModerationInfo:
        return ModerationInfo(backend="llm_classifier:fs-moderation")

    monkeypatch.setattr("app.services.setup.probe_provider", fake_probe)
    monkeypatch.setattr("app.services.setup._moderation_result", fake_moderation)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as public:
        status = await public.get("/api/setup/status")
        assert status.status_code == 200
        body = status.json()
        assert body["complete"] is False
        assert body["started"] is False
        assert body["next_step"] == "admin"
        assert body["steps"] == {
            "admin": False,
            "totp": False,
            "organization": False,
            "provider": False,
            "models": False,
            "moderation": False,
        }

        bad_token = await public.post(
            "/api/setup/admin",
            json={
                "token": "wrong-token",
                "email": ADMIN_EMAIL,
                "password": ADMIN_PASSWORD,
                "display_name": "Operator",
            },
        )
        assert bad_token.status_code == 403
        assert bad_token.json()["code"] == "invalid_setup_token"

        weak = await public.post(
            "/api/setup/admin",
            json={
                "token": SETUP_TOKEN,
                "email": ADMIN_EMAIL,
                "password": "short",
                "display_name": "Operator",
            },
        )
        assert weak.status_code == 422
        assert weak.json()["code"] == "weak_password"

        created = await public.post(
            "/api/setup/admin",
            json={
                "token": SETUP_TOKEN,
                "email": ADMIN_EMAIL,
                "password": ADMIN_PASSWORD,
                "display_name": "Operator",
            },
        )
        assert created.status_code == 201, created.text
        secret = created.json()["totp_secret"]
        assert created.json()["provisioning_uri"].startswith("otpauth://totp/")

        duplicate = await public.post(
            "/api/setup/admin",
            json={
                "token": SETUP_TOKEN,
                "email": "second@test.invalid",
                "password": ADMIN_PASSWORD,
                "display_name": "Second",
            },
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["code"] == "setup_already_started"

        pre_enrolment = await _login(public, ADMIN_EMAIL, ADMIN_PASSWORD, None)
        assert pre_enrolment.status_code == 200
        assert pre_enrolment.json()["totp_setup_required"] is True
        assert "config:manage" not in pre_enrolment.json()["user"]["permissions"]

        wrong_code = await public.post(
            "/api/setup/admin/totp", json={"token": SETUP_TOKEN, "code": "000000"}
        )
        assert wrong_code.status_code == 401
        confirmed = await public.post(
            "/api/setup/admin/totp",
            json={"token": SETUP_TOKEN, "code": pyotp.TOTP(secret).now()},
        )
        assert confirmed.status_code == 200, confirmed.text
        assert len(confirmed.json()["recovery_codes"]) == 8

        login = await _login(public, ADMIN_EMAIL, ADMIN_PASSWORD, pyotp.TOTP(secret).now())
        assert login.status_code == 200, login.text
        assert login.json()["totp_setup_required"] is False
        csrf = login.json()["csrf_token"]
        headers = {"X-CSRF-Token": csrf}

        # The instance is still incomplete: no check, chat or research may start.
        blocked = await public.post("/v1/search", json={"query": "budget"}, headers=headers)
        assert blocked.status_code == 503
        assert blocked.json()["code"] == "setup_required"
        async with app.state.db.session_factory() as session:
            with pytest.raises(AppError) as raised:
                await setup_gate(session)
            assert raised.value.code == "setup_required"

        premature = await public.post("/api/setup/complete", headers=headers)
        assert premature.status_code == 409
        assert premature.json()["code"] == "setup_step_missing"

        organization = await public.post(
            "/api/setup/organization",
            headers=headers,
            json={"name": "Fact Spreader Test", "organization": "Test Org"},
        )
        assert organization.status_code == 200, organization.text
        assert organization.json()["steps"]["organization"] is True

        provider = await public.post(
            "/api/setup/provider",
            headers=headers,
            json={
                "name": "local-llm",
                "base_url": "http://127.0.0.1:11434/v1",
                "is_local": True,
            },
        )
        assert provider.status_code == 200, provider.text
        assert "deepseek-chat" in provider.json()["models"]

        embedding_provider = await public.post(
            "/api/setup/provider",
            headers=headers,
            json={
                "name": "local-embeddings",
                "base_url": "http://127.0.0.1:11434/v1",
                "is_local": True,
                "use": "embedding",
            },
        )
        assert embedding_provider.status_code == 200, embedding_provider.text

        models = await public.post(
            "/api/setup/models",
            headers=headers,
            json={
                "chat_model": "deepseek-chat",
                "embedding_model": "bge-m3",
                "embedding_dim": 1024,
            },
        )
        assert models.status_code == 200, models.text
        assert "fs-embedding" in models.json()["aliases"]

        moderation = await public.post("/api/setup/moderation-test", headers=headers)
        assert moderation.status_code == 200, moderation.text
        assert moderation.json()["flagged"] is False

        final_status = await public.get("/api/setup/status")
        assert final_status.json()["steps"] == {step: True for step in final_status.json()["steps"]}
        assert final_status.json()["next_step"] is None

        completed = await public.post("/api/setup/complete", headers=headers)
        assert completed.status_code == 200, completed.text
        assert completed.json()["complete"] is True

        instance = await public.get("/v1/instance")
        assert instance.status_code == 200
        assert instance.json()["setup_complete"] is True


@pytest.mark.asyncio
async def test_setup_wizard_cannot_run_without_a_configured_token(app: Any) -> None:
    await _empty_database(app)
    app.state.settings.setup_token = SecretStr("")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as public:
        status = await public.get("/api/setup/status")
        assert status.json()["setup_token_required"] is False
        blocked = await public.post(
            "/api/setup/admin",
            json={
                "token": "anything",
                "email": ADMIN_EMAIL,
                "password": ADMIN_PASSWORD,
                "display_name": "Operator",
            },
        )
        assert blocked.status_code == 403
        assert blocked.json()["code"] == "setup_token_not_configured"
