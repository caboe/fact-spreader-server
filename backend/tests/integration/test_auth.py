"""Web login, TOTP enrollment and recovery codes (IMPLEMENT Phase 5)."""

from __future__ import annotations

from typing import Any

import httpx
import pyotp
import pytest

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_totp_enrollment_then_login_requires_a_code_or_recovery_code(app: Any) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        login = await client.post(
            "/api/auth/login",
            json={"email": "admin@test.invalid", "password": "test-admin-password"},
        )
        assert login.status_code == 200, login.text
        assert login.json()["totp_setup_required"] is True
        client.headers["X-CSRF-Token"] = login.json()["csrf_token"]
        setup = await client.post("/api/auth/totp/setup")
        assert setup.status_code == 200, setup.text
        secret = setup.json()["secret"]
        code = pyotp.TOTP(secret).now()
        confirm = await client.post("/api/auth/totp/confirm", json={"code": code})
        assert confirm.status_code == 200, confirm.text
        recovery = confirm.json()["recovery_codes"]
        assert len(recovery) == 8

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as fresh:
        missing = await fresh.post(
            "/api/auth/login",
            json={"email": "admin@test.invalid", "password": "test-admin-password"},
        )
        assert missing.status_code == 403
        assert missing.json()["code"] == "totp_required"
        wrong = await fresh.post(
            "/api/auth/login",
            json={
                "email": "admin@test.invalid",
                "password": "test-admin-password",
                "totp_code": "000000",
            },
        )
        assert wrong.status_code == 401
        assert wrong.json()["code"] == "invalid_totp"
        code = pyotp.TOTP(secret).now()
        valid = await fresh.post(
            "/api/auth/login",
            json={
                "email": "admin@test.invalid",
                "password": "test-admin-password",
                "totp_code": code,
            },
        )
        assert valid.status_code == 200, valid.text

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as recovery_client:
        recovered = await recovery_client.post(
            "/api/auth/login",
            json={
                "email": "admin@test.invalid",
                "password": "test-admin-password",
                "totp_code": recovery[0],
            },
        )
        assert recovered.status_code == 200, recovered.text
        reused = await recovery_client.post(
            "/api/auth/login",
            json={
                "email": "admin@test.invalid",
                "password": "test-admin-password",
                "totp_code": recovery[0],
            },
        )
        assert reused.status_code == 401
