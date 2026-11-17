"""Publisher grades from the shipped CC BY-SA list (PURPOSE §3.1b)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.contracts.api import SourceQualityBasis

GRADE_RANK = {"A": 4, "B": 3, "C": 2, "D": 1}


@dataclass(frozen=True)
class PublisherMatch:
    grade: str
    basis: SourceQualityBasis


class PublisherRegistry:
    """Loads and resolves ``methodology/publishers.json``.

    Resolution is first-match-wins: narrow entries must be listed before broad ones. A
    publisher with no entry is graded ``D`` (unassessed), never assumed reputable.
    """

    def __init__(self, version: str, entries: list[dict[str, Any]]) -> None:
        self.version = version
        self.entries = entries

    @classmethod
    def from_path(cls, path: str | Path) -> PublisherRegistry:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(version=str(data.get("version", "unknown")), entries=data.get("entries", []))

    def resolve(
        self,
        *,
        publisher: str | None,
        url: str | None = None,
        doi: str | None = None,
    ) -> PublisherMatch:
        for entry in self.entries:
            if self._matches(entry, publisher=publisher, url=url, doi=doi):
                grade = str(entry.get("grade", "D"))
                if entry.get("disputed") and GRADE_RANK.get(grade, 0) > GRADE_RANK["C"]:
                    grade = "C"
                return PublisherMatch(
                    grade=grade,
                    basis=SourceQualityBasis(
                        source="local_list" if entry.get("_local_override") else "shipped_list",
                        list_version=self.version,
                        entry=str(entry.get("key") or entry.get("publisher") or "unknown"),
                    ),
                )
        return PublisherMatch(
            grade="D",
            basis=SourceQualityBasis(source="default_unknown", list_version=self.version),
        )

    @staticmethod
    def _matches(
        entry: dict[str, Any],
        *,
        publisher: str | None,
        url: str | None,
        doi: str | None,
    ) -> bool:
        match = entry.get("match") or {}
        host = (urlparse(url).hostname or "").lower() if url else ""
        if host:
            for domain in match.get("domains") or []:
                domain = str(domain).lower().lstrip(".")
                if host == domain or host.endswith(f".{domain}"):
                    return True
        if doi:
            normalized_doi = _normalize_doi(doi)
            for prefix in match.get("doi_prefixes") or []:
                if normalized_doi.startswith(str(prefix).lower()):
                    return True
        if publisher:
            wanted = publisher.casefold().strip()
            names = [
                entry.get("publisher"),
                *(entry.get("aliases") or []),
                *(match.get("aliases") or []),
            ]
            for name in names:
                if name and wanted == str(name).casefold().strip():
                    return True
        return False


def _normalize_doi(doi: str) -> str:
    value = doi.casefold().strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if value.startswith(prefix):
            return value[len(prefix) :]
    return value


def grade_at_least(grade: str, minimum: str) -> bool:
    return GRADE_RANK.get(grade, 0) >= GRADE_RANK.get(minimum, 0)
