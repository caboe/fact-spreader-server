"""Database-backed persona overrides with schema and canonical checks (Phase 6).

The shipped PERSONAS.md stays the source of the Shared Invariants and the default
personas. A local override may tune tone, address, length and rules, or add a persona;
it can never change the invariants, because the API schema does not carry them and the
invariants are always taken from the shipped registry. A canonical test runs the
persona's own example through the deterministic consistency checks; a failure needs
``override_test=true`` to be stored, and that fact is recorded with the override.
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.enums import Verdict
from app.core.errors import AppError
from app.core.ids import utcnow
from app.db.models import Setting
from app.rendering.service import _deterministic_issues
from app.services.personas import PersonaConfig, PersonaRegistry

SETTING_KEY = "personas.overrides"
ADDRESS_MODES = {"direct", "impersonal"}
DIDACTICS = {"answer", "socratic"}
SUBSTANCE_DISPLAY = {"expanded", "compact"}
CHECK_PATTERN = re.compile(r"^(max_questions:\d+|no_exclamation|must_end_with_bottom_line)$")
EDITABLE = (
    "name",
    "description",
    "enabled",
    "address_mode",
    "tone",
    "didactics",
    "moral_framing",
    "verdict_in_text",
    "substance_display",
    "max_words",
    "rules",
    "forbidden",
    "checks",
    "example_output",
)


def parse_overrides(raw: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(raw, dict):
        return {}
    return {
        str(persona_id): dict(value) for persona_id, value in raw.items() if isinstance(value, dict)
    }


async def load_overrides(session: AsyncSession) -> dict[str, dict[str, Any]]:
    row = await session.get(Setting, SETTING_KEY)
    return parse_overrides(row.value.get("personas") if row is not None else None)


def _validate_checks(checks: list[str]) -> list[str]:
    for check in checks:
        if not CHECK_PATTERN.match(check):
            raise AppError(
                422,
                "invalid_check",
                f"Unsupported persona check {check!r}.",
            )
    return checks


def _validate_values(fields: dict[str, Any]) -> dict[str, Any]:
    cleaned = {key: value for key, value in fields.items() if key in EDITABLE}
    if "address_mode" in cleaned and cleaned["address_mode"] not in ADDRESS_MODES:
        raise AppError(422, "invalid_catalog_value", "Unknown address_mode.")
    if "didactics" in cleaned and cleaned["didactics"] not in DIDACTICS:
        raise AppError(422, "invalid_catalog_value", "Unknown didactics.")
    if "substance_display" in cleaned and cleaned["substance_display"] not in SUBSTANCE_DISPLAY:
        raise AppError(422, "invalid_catalog_value", "Unknown substance_display.")
    if "max_words" in cleaned:
        words = int(cleaned["max_words"])
        if not 40 <= words <= 1000:
            raise AppError(422, "invalid_max_words", "max_words must be between 40 and 1000.")
        cleaned["max_words"] = words
    if "checks" in cleaned:
        cleaned["checks"] = _validate_checks([str(item) for item in cleaned["checks"]])
    for field in ("rules", "forbidden"):
        if field in cleaned:
            cleaned[field] = [str(item)[:500] for item in cleaned[field]]
    if "enabled" in cleaned:
        cleaned["enabled"] = bool(cleaned["enabled"])
    return cleaned


def build_persona(
    base: PersonaRegistry, persona_id: str, overrides: dict[str, dict[str, Any]]
) -> PersonaConfig:
    stored = overrides.get(persona_id) or {}
    shipped = base.get(persona_id)
    if shipped is None:
        shipped = PersonaConfig(
            id=persona_id,
            name=str(stored.get("name") or persona_id),
            version=1,
            description=str(stored.get("description") or ""),
            is_default=False,
            enabled=bool(stored.get("enabled", True)),
            address_mode="direct",
            tone="",
            didactics="answer",
            moral_framing=False,
            verdict_in_text=False,
            substance_display="expanded",
            max_words=180,
        )
    fields = {key: value for key, value in stored.items() if key in EDITABLE}
    if fields:
        shipped = replace(shipped, **fields)
    return shipped


def effective_registry(
    base: PersonaRegistry, overrides: dict[str, dict[str, Any]]
) -> PersonaRegistry:
    personas = {persona.id: persona for persona in base.personas.values()}
    for persona_id in overrides:
        personas[persona_id] = build_persona(base, persona_id, overrides)
    default_id = base.default_id if base.default_id in personas else next(iter(personas))
    return PersonaRegistry(
        personas,
        invariants=list(base.invariants),
        default_id=default_id,
    )


def canonical_issues(persona: PersonaConfig) -> list[str]:
    """Run the deterministic checks on the persona's canonical example."""
    text = (persona.example_output or "").strip()
    if not text:
        return []
    allowed = {f"E{number}" for number in re.findall(r"\[E(\d+)\]", text)}
    synthetic = _synthetic_result(text)
    return _deterministic_issues(
        text,
        persona=persona,
        result=synthetic,
        language="en",
        allowed_ids=allowed,
    )


def _synthetic_result(text: str) -> Any:
    """Only the attributes the deterministic checks read; no contract round trip."""
    from types import SimpleNamespace
    from typing import cast

    from app.contracts.api import ArgumentIssue
    from app.rendering.service import _PATTERN_NAMES

    folded = text.casefold()
    issues = [
        ArgumentIssue(pattern=pattern_id, explanation="named in the canonical example")
        for pattern_id, name in _PATTERN_NAMES.items()
        if name in folded
    ]
    return cast(
        Any,
        SimpleNamespace(
            overall_verdict=Verdict.TRUE_BUT_MISLEADING,
            argument_issues=issues,
        ),
    )


async def write_persona(
    session: AsyncSession,
    base: PersonaRegistry,
    persona_id: str,
    fields: dict[str, Any],
    *,
    override_test: bool,
    actor_id: str | None,
) -> PersonaConfig:
    if not re.match(r"^[a-z][a-z0-9_-]{1,40}$", persona_id):
        raise AppError(422, "invalid_persona_id", "Use lowercase letters, digits, - and _.")
    overrides = await load_overrides(session)
    existing = overrides.get(persona_id)
    cleaned = _validate_values(fields)
    if base.get(persona_id) is None and existing is None and not cleaned.get("name"):
        raise AppError(422, "name_required", "A new persona needs a name.")
    stored = {**(existing or {}), **cleaned}
    if override_test:
        stored["test_override"] = True
    candidate = build_persona(base, persona_id, {persona_id: stored})
    issues = canonical_issues(candidate)
    if issues and not override_test:
        raise AppError(
            422,
            "persona_test_failed",
            "The canonical test failed: " + "; ".join(issues),
            extra={"issues": issues},
        )
    stored["test_issues"] = issues
    overrides[persona_id] = stored
    row = await session.get(Setting, SETTING_KEY)
    value = {"personas": overrides}
    if row is None:
        session.add(Setting(key=SETTING_KEY, value=value, updated_at=utcnow()))
    else:
        row.value = value
        row.updated_at = utcnow()
    await session.commit()
    return candidate


async def delete_persona(session: AsyncSession, base: PersonaRegistry, persona_id: str) -> None:
    if base.get(persona_id) is not None:
        raise AppError(
            422,
            "shipped_persona",
            "A shipped persona is disabled, not deleted.",
        )
    overrides = await load_overrides(session)
    if persona_id not in overrides:
        raise AppError(404, "not_found", "The persona does not exist.")
    del overrides[persona_id]
    row = await session.get(Setting, SETTING_KEY)
    assert row is not None
    row.value = {"personas": overrides}
    row.updated_at = utcnow()
    await session.commit()


async def effective_personas(session: AsyncSession, path: str) -> PersonaRegistry:
    return effective_registry(PersonaRegistry.from_path(path), await load_overrides(session))
