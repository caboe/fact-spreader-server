"""Methodology content: confounder checklists and the argument-pattern taxonomy."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Confounder:
    id: str
    label: str
    retrieval_hint: str
    retrieval_hint_de: str | None = None


@dataclass(frozen=True)
class Checklist:
    topic: str
    name: str
    version: str
    domain_tags: tuple[str, ...]
    staleness_days: int
    confounders: tuple[Confounder, ...]


class Methodology:
    def __init__(
        self,
        *,
        checklists: dict[str, Checklist],
        patterns: dict[str, dict[str, Any]],
        patterns_version: str,
    ) -> None:
        self.checklists = checklists
        self.patterns = patterns
        self.patterns_version = patterns_version

    @classmethod
    def load(cls, checklist_dir: str | Path, pattern_path: str | Path) -> Methodology:
        checklists: dict[str, Checklist] = {}
        for path in sorted(Path(checklist_dir).glob("*.json")):
            raw = json.loads(path.read_text(encoding="utf-8"))
            topic = str(raw["topic"])
            checklists[topic] = Checklist(
                topic=topic,
                name=str(raw["name"]),
                version=str(raw.get("version", "unknown")),
                domain_tags=tuple(str(tag) for tag in raw.get("domain_tags", [])),
                staleness_days=int(raw.get("staleness_days", 1095)),
                confounders=tuple(
                    Confounder(
                        id=str(item["id"]),
                        label=str(item.get("label", item["id"])),
                        retrieval_hint=str(item.get("retrieval_hint", "")),
                        retrieval_hint_de=item.get("retrieval_hint_de"),
                    )
                    for item in raw.get("confounders", [])
                ),
            )
        patterns_raw = json.loads(Path(pattern_path).read_text(encoding="utf-8"))
        patterns = {
            str(item["id"]): item for item in patterns_raw.get("patterns", []) if "id" in item
        }
        return cls(
            checklists=checklists,
            patterns=patterns,
            patterns_version=str(patterns_raw.get("version", "unknown")),
        )

    def confounders_for(self, topics: list[str]) -> list[Confounder]:
        seen: dict[str, Confounder] = {}
        for topic in topics:
            checklist = self.checklists.get(topic)
            if checklist is None:
                continue
            for confounder in checklist.confounders:
                seen.setdefault(confounder.id, confounder)
        return list(seen.values())

    def staleness_days_for(self, topics: list[str]) -> int:
        values = [
            self.checklists[topic].staleness_days for topic in topics if topic in self.checklists
        ]
        return min(values) if values else 1095

    def domain_tags_for(self, topics: list[str]) -> list[str]:
        tags: list[str] = []
        for topic in topics:
            checklist = self.checklists.get(topic)
            if checklist:
                for tag in checklist.domain_tags:
                    if tag not in tags:
                        tags.append(tag)
        return tags
