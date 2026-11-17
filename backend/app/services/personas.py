"""Runtime persona configuration parsed from PERSONAS.md (PERSONAS.md, PURPOSE §3.13).

The Markdown file is the source of truth: the YAML blocks determine the seeded personas
and the Shared Invariants are injected into every rendering. This parser deliberately keeps
the file human-editable; no persona content is duplicated in Python.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass(frozen=True)
class PersonaConfig:
    id: str
    name: str
    version: int
    description: str
    is_default: bool
    enabled: bool
    address_mode: str
    tone: str
    didactics: str
    moral_framing: bool
    verdict_in_text: bool
    substance_display: str
    max_words: int
    rules: tuple[str, ...] = field(default_factory=tuple)
    forbidden: tuple[str, ...] = field(default_factory=tuple)
    checks: tuple[str, ...] = field(default_factory=tuple)
    example_output: str = ""


class PersonaConfigError(RuntimeError):
    pass


class PersonaRegistry:
    def __init__(
        self, personas: dict[str, PersonaConfig], *, invariants: list[str], default_id: str
    ) -> None:
        self.personas = personas
        self.invariants = invariants
        self.default_id = default_id

    @classmethod
    def from_path(cls, path: str | Path) -> PersonaRegistry:
        text = Path(path).read_text(encoding="utf-8")
        personas: dict[str, PersonaConfig] = {}
        pattern = re.compile(r"^## \d+\. .*?\n\n```yaml\n(.*?)```", re.DOTALL | re.MULTILINE)
        for match in pattern.finditer(text):
            raw = yaml.safe_load(match.group(1)) or {}
            persona_id = str(raw.get("id", "")).strip()
            if not persona_id or persona_id == "string":
                continue
            try:
                persona = PersonaConfig(
                    id=persona_id,
                    name=str(raw["name"]),
                    version=int(raw.get("version", 1)),
                    description=str(raw.get("description", "")),
                    is_default=bool(raw.get("is_default", True)),
                    enabled=bool(raw.get("enabled", True)),
                    address_mode=str(raw.get("address_mode", "direct")),
                    tone=str(raw.get("tone", "")),
                    didactics=str(raw.get("didactics", "answer")),
                    moral_framing=bool(raw.get("moral_framing", False)),
                    verdict_in_text=bool(raw.get("verdict_in_text", False)),
                    substance_display=str(raw.get("substance_display", "expanded")),
                    max_words=int(raw.get("max_words", 180)),
                    rules=tuple(str(item) for item in raw.get("rules", [])),
                    forbidden=tuple(str(item) for item in raw.get("forbidden", [])),
                    checks=tuple(str(item) for item in raw.get("checks", [])),
                    example_output=str(raw.get("example_output", "")),
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise PersonaConfigError(f"invalid persona block {persona_id!r}: {exc}") from exc
            personas[persona_id] = persona
        if not personas:
            raise PersonaConfigError(f"no persona YAML blocks found in {path}")
        invariants = _parse_invariants(text)
        if not invariants:
            raise PersonaConfigError(f"no Shared Invariants found in {path}")
        default_id = "analyst" if "analyst" in personas else next(iter(personas))
        return cls(personas, invariants=invariants, default_id=default_id)

    def get(self, persona_id: str) -> PersonaConfig | None:
        return self.personas.get(persona_id)

    def enabled(self) -> list[PersonaConfig]:
        return [persona for persona in self.personas.values() if persona.enabled]

    def resolve(self, persona_id: str | None) -> PersonaConfig:
        resolved = self.get(persona_id or self.default_id)
        if resolved is None or not resolved.enabled:
            raise PersonaConfigError(f"persona {persona_id!r} is not enabled")
        return resolved


def _parse_invariants(text: str) -> list[str]:
    if "## Shared Invariants" not in text:
        return []
    section = text.split("## Shared Invariants", 1)[1]
    section = section.split("### What the consistency checker verifies", 1)[0]
    invariants: list[str] = []
    current: list[str] = []
    for line in section.splitlines():
        match = re.match(r"^(\d+)\.\s+(.*)$", line)
        if match:
            if current:
                invariants.append(" ".join(current).strip())
            current = [match.group(2).strip()]
        elif current and line.strip() and not line.startswith("#"):
            current.append(line.strip())
        elif current and not line.strip():
            invariants.append(" ".join(current).strip())
            current = []
    if current:
        invariants.append(" ".join(current).strip())
    return [item for item in invariants if item]
