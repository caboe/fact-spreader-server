"""The permission matrix: every protected route, every credential (IMPLEMENT Phase 5).

The route table is read from the FastAPI application, not copied into the test, so a new
endpoint that forgets ``require_permission`` fails the anonymous check and a wrong
permission is caught route by route.
"""

from __future__ import annotations

import re
from typing import Any

import httpx
import pytest
from app.contracts.enums import PERMISSIONS
from app.core.ids import new_id, utcnow
from app.core.security import hash_password
from app.db.models import ApiKey, User
from app.services.auth import create_api_key, effective_permissions
from fastapi.routing import APIRoute
from sqlalchemy import select

pytestmark = pytest.mark.integration

PUBLIC_PATHS = {
    "/healthz",
    "/readyz",
    "/v1/instance",
    "/api/auth/login",
    "/api/auth/logout",
    "/api/setup/status",
    "/api/setup/admin",
    "/api/setup/admin/totp",
}


def _permission_from(route: APIRoute) -> str | None:
    def walk(dependency: Any) -> str | None:
        call = getattr(dependency, "call", None)
        for cell in getattr(call, "__closure__", None) or ():
            try:
                value = cell.cell_contents
            except ValueError:  # pragma: no cover - empty cell
                continue
            if isinstance(value, str) and value in PERMISSIONS:
                return value
        for child in getattr(dependency, "dependencies", ()) or ():
            found = walk(child)
            if found:
                return found
        return None

    for dependency in route.dependant.dependencies:
        found = walk(dependency)
        if found:
            return found
    return None


def _iter_api_routes(app: Any) -> list[APIRoute]:
    """Flatten the router wrappers of this FastAPI version into APIRoute objects."""
    found: list[APIRoute] = []
    stack = list(app.routes)
    while stack:
        route = stack.pop()
        if isinstance(route, APIRoute):
            found.append(route)
            continue
        included = getattr(route, "original_router", None)
        if included is not None:
            stack.extend(included.routes)
        else:
            stack.extend(getattr(route, "routes", ()) or ())
    return found


def _protected_routes(app: Any) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    for route in _iter_api_routes(app):
        if route.path.startswith(("/internal/", "/docs")):
            continue
        permission = _permission_from(route)
        if permission is None:
            continue
        method = sorted(route.methods - {"HEAD", "OPTIONS"})[0]
        rows.append((method, route.path, permission))
    return rows


def _request_path(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "unknown", path)


async def _user_with_key(
    app: Any,
    *,
    roles: list[str] | None = None,
    permissions: list[str] | None = None,
    denied: list[str] | None = None,
    key_permissions: list[str] | None = None,
    key_limits: dict[str, int] | None = None,
) -> tuple[User, str, ApiKey]:
    async with app.state.db.session_factory() as session:
        user = User(
            id=new_id("usr"),
            email=f"matrix-{new_id('x')}@test.invalid",
            display_name="Matrix",
            password_hash=hash_password("correct-horse-battery-9"),
            roles=roles or [],
            permissions=permissions or [],
            denied_permissions=denied or [],
            is_active=True,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        session.add(user)
        await session.flush()
        key, plaintext = await create_api_key(
            session,
            user=user,
            name="matrix",
            permissions=key_permissions if key_permissions is not None else None,
            limits=key_limits,
        )
        await session.commit()
        return user, plaintext, key


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_every_protected_route_allows_its_permission_and_denies_others(app: Any) -> None:
    routes = _protected_routes(app)
    assert len(routes) >= 20
    assert {permission for _, _, permission in routes} <= set(PERMISSIONS)

    empty_user, empty_key, _ = await _user_with_key(app)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        for method, path, permission in routes:
            _owner, token, _ = await _user_with_key(
                app, permissions=[permission], key_permissions=[permission]
            )
            allowed = await client.request(
                method, _request_path(path), headers=_auth(token), json={}
            )
            assert allowed.status_code != 403, (
                f"{method} {path} requires {permission} but denied a key holding it: "
                f"{allowed.status_code} {allowed.text}"
            )
            denied = await client.request(
                method, _request_path(path), headers=_auth(empty_key), json={}
            )
            assert denied.status_code == 403, (
                f"{method} {path} ({permission}) let a credential without it through: "
                f"{denied.status_code} {denied.text}"
            )
            assert denied.json()["code"] == "permission_denied"
    assert effective_permissions(empty_user) == frozenset()


@pytest.mark.asyncio
async def test_every_non_public_route_rejects_anonymous_callers(app: Any) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        for route in _iter_api_routes(app):
            if route.path.startswith(("/internal/", "/docs")):
                continue
            if route.path in PUBLIC_PATHS or route.path in {"/openapi.json", "/redoc"}:
                continue
            method = sorted(route.methods - {"HEAD", "OPTIONS"})[0]
            response = await client.request(method, _request_path(route.path), json={})
            assert response.status_code == 401, (
                f"{method} {route.path} answered {response.status_code} without credentials"
            )


@pytest.mark.asyncio
async def test_a_key_cannot_hold_a_permission_its_owner_lacks(app: Any) -> None:
    _user, token, key = await _user_with_key(app, key_permissions=["users:manage"])
    assert key.permissions == []
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/users", headers=_auth(token))
    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"


@pytest.mark.asyncio
async def test_two_roles_give_the_union_and_an_explicit_denial_overrides_it(app: Any) -> None:
    _user, token, _key = await _user_with_key(app, roles=["editor", "researcher"])
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        queue = await client.get("/v1/review/queue", headers=_auth(token))
        assert queue.status_code == 200, queue.text
        users = await client.get("/v1/users", headers=_auth(token))
        assert users.status_code == 403
        assert users.json()["code"] == "permission_denied"
    _denied_user, denied_token, denied_key = await _user_with_key(
        app,
        roles=["editor"],
        denied=["documents:review"],
        key_permissions=["documents:review"],
    )
    assert denied_key.permissions == []
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        denied = await client.get("/v1/review/queue", headers=_auth(denied_token))
    assert denied.status_code == 403
    assert denied.json()["code"] == "permission_denied"


@pytest.mark.asyncio
async def test_revoked_api_key_stops_working_immediately(app: Any) -> None:
    async with app.state.db.session_factory() as session:
        admin = (
            await session.execute(select(User).where(User.email == "admin@test.invalid"))
        ).scalar_one()
        key, token = await create_api_key(session, user=admin, name="to-revoke")
        await session.commit()
        key_id = key.id
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/v1/claims", headers=_auth(token))).status_code == 200
        async with app.state.db.session_factory() as session:
            row = await session.get(ApiKey, key_id)
            assert row is not None
            row.revoked_at = utcnow()
            await session.commit()
        revoked = await client.get("/v1/claims", headers=_auth(token))
    assert revoked.status_code == 401
    assert revoked.json()["code"] == "authentication_required"


@pytest.mark.asyncio
async def test_a_device_token_defaults_to_claims_submit_and_dies_on_revocation(app: Any) -> None:
    _user, user_token, _key = await _user_with_key(
        app, roles=["user"], key_permissions=["devices:manage", "claims:submit"]
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/v1/devices", json={"name": "Browser extension"}, headers=_auth(user_token)
        )
        assert created.status_code == 201, created.text
        device = created.json()["device"]
        device_token = created.json()["token"]
        assert device["permissions"] == ["claims:submit"]

        documents = await client.post(
            "/v1/documents",
            json={"input": {"type": "text", "text": "A document."}},
            headers=_auth(device_token),
        )
        assert documents.status_code == 403
        users = await client.get("/v1/users", headers=_auth(device_token))
        assert users.status_code == 403

        escalation = await client.post(
            "/v1/devices",
            json={"name": "greedy", "permissions": ["documents:submit"]},
            headers=_auth(user_token),
        )
        assert escalation.status_code == 422
        assert escalation.json()["code"] == "permission_escalation"

        revoked = await client.delete(f"/v1/devices/{device['id']}", headers=_auth(user_token))
        assert revoked.status_code == 204
        after = await client.get("/v1/claims", headers=_auth(device_token))
        assert after.status_code == 401


@pytest.mark.asyncio
async def test_a_manager_cannot_grant_more_than_they_hold(app: Any) -> None:
    _manager, manager_key, _ = await _user_with_key(
        app, permissions=["users:manage"], key_permissions=["users:manage"]
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/users",
            headers=_auth(manager_key),
            json={
                "email": "beyond@test.invalid",
                "display_name": "Beyond",
                "password": "beyond-password-9",
                "roles": ["editor"],
            },
        )
    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"
