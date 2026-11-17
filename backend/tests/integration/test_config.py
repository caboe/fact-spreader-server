"""Provider/model registry, capability tests, role validation and data flow (Phase 6)."""

from __future__ import annotations

from typing import Any, ClassVar

import httpx
import pytest
from app.api.internal import llm as gateway
from app.db.models import Provider, UsageEvent
from app.services.capability_probes import ProbeResult
from app.services.providers import box
from sqlalchemy import select

pytestmark = pytest.mark.integration


async def _fake_probe(
    capability: str,
    provider: Any,
    model: Any,
    settings: Any,
    *,
    transport: Any = None,
) -> ProbeResult:
    return ProbeResult(
        capability,
        "tested",
        "fake_probe",
        1024 if capability == "embedding" else None,
        1,
    )


async def _provider(client: httpx.AsyncClient, name: str, *, is_local: bool = False) -> Any:
    response = await client.post(
        "/v1/config/providers",
        json={
            "name": name,
            "base_url": "http://local.example.invalid/v1"
            if is_local
            else "https://api.example.invalid/v1",
            "api_key": None if is_local else "sk-secret-value",
            "is_local": is_local,
            "test_connection": True,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["provider"]


async def _model(client: httpx.AsyncClient, provider_id: str, name: str) -> Any:
    response = await client.post(
        "/v1/config/models",
        json={
            "provider_id": provider_id,
            "model_name": name,
            "capabilities": ["chat", "structured_output"],
            "context_window": 16000,
            "multilingual": True,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.asyncio
async def test_provider_keys_stay_encrypted_and_role_assignment_uses_tested_capabilities(
    client: httpx.AsyncClient, app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_discovery(base_url: str, api_key: str | None) -> list[str]:
        return ["model-a", "model-b"]

    monkeypatch.setattr("app.services.registry.probe_provider", fake_discovery)
    monkeypatch.setattr("app.services.capability_probes.probe_capability", _fake_probe)

    created = await client.post(
        "/v1/config/providers",
        json={
            "name": "external-chat",
            "base_url": "https://api.example.invalid/v1",
            "api_key": "sk-secret-value",
            "test_connection": True,
        },
    )
    assert created.status_code == 201, created.text
    assert "sk-secret-value" not in created.text
    provider = created.json()["provider"]
    assert provider["has_key"] is True
    assert created.json()["models"] == ["model-a", "model-b"]

    async with app.state.db.session_factory() as session:
        row = (
            await session.execute(select(Provider).where(Provider.id == provider["id"]))
        ).scalar_one()
        assert row.api_key_enc is not None
        assert b"sk-secret-value" not in bytes(row.api_key_enc)
        assert box(app.state.settings).decrypt(row.api_key_enc) == "sk-secret-value"

    model = await _model(client, provider["id"], "model-a")
    assert model["tested_capabilities"] == []

    unsupported = await client.put("/v1/config/roles/fs-vision", json={"model_id": model["id"]})
    assert unsupported.status_code == 422
    assert unsupported.json()["code"] == "assignment_rejected"
    assert "missing_capability:vision" in unsupported.json()["reasons"]

    probed = await client.post(f"/v1/config/models/{model['id']}/probe", json={"capabilities": []})
    assert probed.status_code == 200, probed.text
    assert {result["status"] for result in probed.json()["results"]} == {"tested"}
    async with app.state.db.session_factory() as session:
        probe_events = (
            (await session.execute(select(UsageEvent).where(UsageEvent.consumer == "probe")))
            .scalars()
            .all()
        )
        assert len(probe_events) == 2
        assert {event.role for event in probe_events} == {"probe:chat", "probe:structured_output"}

    assigned = await client.put("/v1/config/roles/fs-extract", json={"model_id": model["id"]})
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["model"]["gateway_alias"] == "fs-extract"
    assert assigned.json()["suitable"] is True

    roles = await client.get("/v1/config/roles")
    by_alias = {role["alias"]: role for role in roles.json()}
    assert by_alias["fs-extract"]["suitable"] is True
    assert by_alias["fs-vision"]["suitable"] is False

    models = await client.get("/v1/config/models")
    base = next(row for row in models.json() if row["id"] == model["id"])
    assert base["tested_capabilities"] == ["chat", "structured_output"]
    assert base["gateway_alias"] is None


class _FakeHTTP:
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
        _FakeHTTP.calls.append(url)
        return httpx.Response(
            200,
            json={
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}}],
                "usage": {"prompt_tokens": 2, "completion_tokens": 1},
            },
        )


@pytest.mark.asyncio
async def test_data_flow_blocks_before_transport_and_uses_only_an_allowed_fallback(
    client: httpx.AsyncClient, app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.services.registry.probe_provider", _fake_provider_list)
    monkeypatch.setattr("app.services.capability_probes.probe_capability", _fake_probe)
    external = await _provider(client, "external-chat")
    external_model = await _model(client, external["id"], "external-model")
    await client.post(f"/v1/config/models/{external_model['id']}/probe", json={})
    assigned = await client.put("/v1/config/roles/fs-chat", json={"model_id": external_model["id"]})
    assert assigned.status_code == 200, assigned.text

    local = await _provider(client, "local-chat", is_local=True)
    local_model = await _model(client, local["id"], "local-model")
    await client.post(f"/v1/config/models/{local_model['id']}/probe", json={})
    fallback = await client.put("/v1/config/roles/fs-verify", json={"model_id": local_model["id"]})
    assert fallback.status_code == 200, fallback.text

    blocked = await client.put(
        "/v1/config/data-flow", json={"allow_external": False, "fallback_alias": None}
    )
    assert blocked.status_code == 200

    _FakeHTTP.calls = []
    monkeypatch.setattr(gateway, "OutboundHTTP", _FakeHTTP)
    headers = {
        "Authorization": f"Bearer {app.state.settings.internal_llm_key.get_secret_value()}",
        "X-FS-Consumer": "pipeline",
        "X-FS-Data-Classes": "user_input",
        "X-FS-Purpose": "query",
    }
    body = {
        "model": "fs-chat",
        "messages": [{"role": "user", "content": "some user text"}],
    }
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as internal:
        refused = await internal.post(
            "/internal/llm/v1/chat/completions", json=body, headers=headers
        )
        assert refused.status_code == 403, refused.text
        assert refused.json()["error"]["code"] == "data_flow_blocked"
        # The transport test: no request reached the forbidden provider at all.
        assert _FakeHTTP.calls == []

        allowed = await client.put(
            "/v1/config/data-flow",
            json={"allow_external": False, "fallback_alias": "fs-verify"},
        )
        assert allowed.status_code == 200
        served = await internal.post(
            "/internal/llm/v1/chat/completions", json=body, headers=headers
        )
        assert served.status_code == 200, served.text
        assert len(_FakeHTTP.calls) == 1
        assert _FakeHTTP.calls[0].startswith("http://local.example.invalid/v1")

    restored = await client.put(
        "/v1/config/data-flow", json={"allow_external": True, "fallback_alias": None}
    )
    assert restored.status_code == 200


async def _fake_provider_list(base_url: str, api_key: str | None) -> list[str]:
    return ["model-a"]
