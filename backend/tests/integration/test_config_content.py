"""Persona and methodology overrides: schema, catalog, canonical test and invariants."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_personas_accept_local_overrides_and_never_the_shared_invariants(
    client: httpx.AsyncClient, app: Any
) -> None:
    invariants = await client.get("/v1/config/personas")
    assert invariants.status_code == 200, invariants.text
    shipped = {item["id"]: item for item in invariants.json()}
    assert "analyst" in shipped
    assert shipped["analyst"]["custom"] is False

    changed = await client.put(
        "/v1/config/personas/analyst",
        json={"tone": "precise and calm", "checks": ["no_exclamation"]},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["overridden"] is True
    assert changed.json()["tone"] == "precise and calm"
    assert app.state.personas.get("analyst").tone == "precise and calm"  # type: ignore[union-attr]
    assert app.state.personas.invariants == app.state.persona_base.invariants

    custom = await client.put(
        "/v1/config/personas/zen",
        json={
            "name": "Zen",
            "tone": "calm",
            "checks": ["no_exclamation"],
            "example_output": "A calm sample without exclamation marks.",
        },
    )
    assert custom.status_code == 200, custom.text
    assert custom.json()["custom"] is True

    invariants_attempt = await client.put(
        "/v1/config/personas/analyst",
        json={"invariants": ["Never cite evidence."]},
    )
    assert invariants_attempt.status_code == 422

    bad_catalog = await client.put("/v1/config/personas/analyst", json={"address_mode": "shout"})
    assert bad_catalog.status_code == 422
    bad_check = await client.put(
        "/v1/config/personas/analyst", json={"checks": ["drop_invariants"]}
    )
    assert bad_check.status_code == 422
    assert bad_check.json()["code"] == "invalid_check"

    failing = await client.put(
        "/v1/config/personas/noisy",
        json={
            "name": "Noisy",
            "checks": ["no_exclamation"],
            "example_output": "This sample is loud!",
        },
    )
    assert failing.status_code == 422
    assert failing.json()["code"] == "persona_test_failed"
    assert any("exclamation" in issue for issue in failing.json()["issues"])
    overridden = await client.put(
        "/v1/config/personas/noisy",
        json={
            "name": "Noisy",
            "checks": ["no_exclamation"],
            "example_output": "This sample is loud!",
            "override_test": True,
        },
    )
    assert overridden.status_code == 200, overridden.text
    assert overridden.json()["test_issues"]

    delete_shipped = await client.delete("/v1/config/personas/analyst")
    assert delete_shipped.status_code == 422
    delete_custom = await client.delete("/v1/config/personas/zen")
    assert delete_custom.status_code == 204
    listed = {item["id"] for item in (await client.get("/v1/config/personas")).json()}
    assert "zen" not in listed


@pytest.mark.asyncio
async def test_methodology_overrides_bump_a_local_version_and_validate_ids(
    client: httpx.AsyncClient, app: Any
) -> None:
    before = await client.get("/v1/config/methodology")
    assert before.status_code == 200, before.text
    assert before.json()["version"] == 0
    assert len(before.json()["checklists"]) >= 1

    pattern = await client.put(
        "/v1/config/methodology/patterns/composition_effect",
        json={"name": "Composition effect (local)"},
    )
    assert pattern.status_code == 200, pattern.text
    assert pattern.json()["version"] == 1
    patterns = {item["id"]: item for item in pattern.json()["patterns"]}
    assert patterns["composition_effect"]["name"] == "Composition effect (local)"
    assert "+local." in pattern.json()["patterns_version"]
    assert (
        app.state.methodology.patterns["composition_effect"]["name"] == "Composition effect (local)"
    )

    checklist = await client.put(
        "/v1/config/methodology/checklists/crime_statistics",
        json={
            "staleness_days": 30,
            "confounders": [{"id": "age", "label": "age mix"}],
        },
    )
    assert checklist.status_code == 200, checklist.text
    assert checklist.json()["version"] == 2
    crime = next(
        item for item in checklist.json()["checklists"] if item["topic"] == "crime_statistics"
    )
    assert crime["staleness_days"] == 30
    age = next(item for item in crime["confounders"] if item["id"] == "age")
    assert age["label"] == "age mix"

    unknown_pattern = await client.put(
        "/v1/config/methodology/patterns/not_a_pattern", json={"name": "x"}
    )
    assert unknown_pattern.status_code == 422
    assert unknown_pattern.json()["code"] == "unknown_pattern"
    unknown_confounder = await client.put(
        "/v1/config/methodology/checklists/crime_statistics",
        json={"confounders": [{"id": "not_a_confounder"}]},
    )
    assert unknown_confounder.status_code == 422
    assert unknown_confounder.json()["code"] == "unknown_confounder"
