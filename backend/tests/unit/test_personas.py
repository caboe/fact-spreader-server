"""PERSONAS.md is runtime input; the parser and invariants are load-bearing."""

from __future__ import annotations

from pathlib import Path

from app.services.personas import PersonaRegistry

ROOT = Path(__file__).resolve().parents[3]


def registry() -> PersonaRegistry:
    return PersonaRegistry.from_path(ROOT / "PERSONAS.md")


def test_the_three_v1_personas_are_parsed() -> None:
    personas = registry()
    assert set(personas.personas) == {"analyst", "mediator", "straight-talker"}
    assert personas.default_id == "analyst"
    assert all(persona.enabled for persona in personas.enabled())


def test_shared_invariants_are_parsed_and_not_empty() -> None:
    personas = registry()
    assert len(personas.invariants) >= 10
    assert any("Never alter substance" in item for item in personas.invariants)


def test_analyst_is_impersonal_and_has_the_mechanical_check() -> None:
    analyst = registry().resolve("analyst")
    assert analyst.address_mode == "impersonal"
    assert "no_second_person" in analyst.checks


def test_config_carries_address_mode_and_forbidden_rules() -> None:
    mediator = registry().resolve("mediator")
    assert mediator.address_mode == "direct"
    assert mediator.forbidden
    straight = registry().resolve("straight-talker")
    assert straight.moral_framing is True
