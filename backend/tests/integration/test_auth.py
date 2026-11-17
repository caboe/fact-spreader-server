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


@pytest.mark.asyncio
async def test_privileged_permissions_require_totp_and_password_reset_ends_sessions(
    app: Any,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as admin:
        login = await admin.post(
            "/api/auth/login",
            json={"email": "admin@test.invalid", "password": "test-admin-password"},
        )
        assert login.status_code == 200
        assert login.json()["totp_setup_required"] is True
        assert "users:manage" not in login.json()["user"]["permissions"]
        admin.headers["X-CSRF-Token"] = login.json()["csrf_token"]

        blocked = await admin.post(
            "/v1/users",
            json={
                "email": "blocked@test.invalid",
                "display_name": "Blocked",
                "password": "editor-password-1",
                "roles": ["user"],
            },
        )
        assert blocked.status_code == 403
        assert blocked.json()["code"] == "totp_setup_required"

        setup = await admin.post("/api/auth/totp/setup")
        secret = setup.json()["secret"]
        await admin.post("/api/auth/totp/confirm", json={"code": pyotp.TOTP(secret).now()})

        created = await admin.post(
            "/v1/users",
            json={
                "email": "member@test.invalid",
                "display_name": "Editor",
                "password": "editor-password-1",
                "roles": ["user"],
            },
        )
        assert created.status_code == 201, created.text
        editor_id = created.json()["id"]

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as editor:
        login = await editor.post(
            "/api/auth/login",
            json={"email": "member@test.invalid", "password": "editor-password-1"},
        )
        assert login.status_code == 200
        assert login.json()["totp_setup_required"] is False
        claims = await editor.get("/v1/claims")
        assert claims.status_code == 200
        denied = await editor.get("/v1/users")
        assert denied.status_code == 403
        assert denied.json()["code"] == "permission_denied"

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as admin:
        login = await admin.post(
            "/api/auth/login",
            json={
                "email": "admin@test.invalid",
                "password": "test-admin-password",
                "totp_code": pyotp.TOTP(secret).now(),
            },
        )
        assert login.status_code == 200
        admin.headers["X-CSRF-Token"] = login.json()["csrf_token"]
        reset = await admin.post(
            f"/v1/users/{editor_id}/password",
            json={"password": "fresh-editor-secret-9"},
        )
        assert reset.status_code == 204, reset.text

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as editor:
        old_session = await editor.get("/v1/claims")
        assert old_session.status_code == 401
        old_password = await editor.post(
            "/api/auth/login",
            json={"email": "member@test.invalid", "password": "editor-password-1"},
        )
        assert old_password.status_code == 401
        new_password = await editor.post(
            "/api/auth/login",
            json={"email": "member@test.invalid", "password": "fresh-editor-secret-9"},
        )
        assert new_password.status_code == 200
