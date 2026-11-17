"""Local publisher-list overrides (IMPLEMENT Phase 6).

The shipped list is the baseline; a local override replaces one entry's grade or disputed
flag without editing the shipped file. The effective list is rebuilt per worker job, so a
re-check grades retrieved documents with the new value. A disputed entry is capped at C,
exactly like the shipped rule. Overrides never add a publisher: an unknown key is a 422,
because an unreviewed new entry could silently upgrade a source.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.ids import utcnow
from app.db.models import ClaimCache, Result, Setting
from app.services.publishers import GRADE_RANK, PublisherRegistry

SETTING_KEY = "publishers.overrides"
FIELDS = ("grade", "disputed", "note")


@dataclass(frozen=True)
class Override:
    key: str
    grade: str | None = None
    disputed: bool | None = None
    note: str | None = None


def parse_overrides(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    parsed: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        if not key:
            continue
        entry: dict[str, Any] = {"key": key}
        for field in FIELDS:
            if item.get(field) is not None:
                entry[field] = item[field]
        parsed.append(entry)
    return parsed


async def load_overrides(session: AsyncSession) -> list[dict[str, Any]]:
    row = await session.get(Setting, SETTING_KEY)
    return parse_overrides(row.value.get("entries") if row is not None else None)


def validate_overrides(
    base: PublisherRegistry, entries: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    shipped = {str(entry.get("key")): entry for entry in base.entries if entry.get("key")}
    seen: set[str] = set()
    cleaned: list[dict[str, Any]] = []
    for entry in entries:
        key = str(entry["key"])
        if key not in shipped:
            raise AppError(422, "unknown_publisher_key", f"No shipped publisher entry {key!r}.")
        if key in seen:
            raise AppError(422, "duplicate_publisher_key", f"Duplicate override for {key!r}.")
        seen.add(key)
        grade = entry.get("grade")
        if grade is not None and grade not in GRADE_RANK:
            raise AppError(422, "invalid_grade", "The grade must be A, B, C or D.")
        cleaned_entry: dict[str, Any] = {"key": key}
        if grade is not None:
            cleaned_entry["grade"] = grade
        if entry.get("disputed") is not None:
            cleaned_entry["disputed"] = bool(entry["disputed"])
        if entry.get("note") is not None:
            cleaned_entry["note"] = str(entry["note"])[:300]
        cleaned.append(cleaned_entry)
    return cleaned


def version_for(base: PublisherRegistry, overrides: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256(json.dumps(overrides, sort_keys=True).encode()).hexdigest()[:8]
    return f"{base.version}+local:{digest}" if overrides else base.version


def effective_registry(
    base: PublisherRegistry, overrides: list[dict[str, Any]]
) -> PublisherRegistry:
    by_key = {str(entry["key"]): entry for entry in overrides}
    entries: list[dict[str, Any]] = []
    for shipped in base.entries:
        key = str(shipped.get("key") or "")
        override = by_key.get(key)
        if override is None:
            entries.append(shipped)
            continue
        merged = dict(shipped)
        if override.get("grade") is not None:
            merged["grade"] = override["grade"]
        if override.get("disputed") is not None:
            merged["disputed"] = override["disputed"]
        merged["_local_override"] = True
        merged["_override_note"] = override.get("note")
        entries.append(merged)
    return PublisherRegistry(version=version_for(base, overrides), entries=entries)


async def effective_publishers(session: AsyncSession, base_path: str) -> PublisherRegistry:
    base = PublisherRegistry.from_path(base_path)
    return effective_registry(base, await load_overrides(session))


def diff(base: PublisherRegistry, overrides: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key = {str(entry["key"]): entry for entry in overrides}
    changes: list[dict[str, Any]] = []
    for shipped in base.entries:
        key = str(shipped.get("key") or "")
        override = by_key.get(key)
        if override is None:
            continue
        for field in ("grade", "disputed"):
            before = shipped.get(field)
            if override.get(field) is not None and override[field] != before:
                changes.append(
                    {
                        "key": key,
                        "publisher": shipped.get("publisher"),
                        "field": field,
                        "shipped": before,
                        "local": override[field],
                    }
                )
    return changes


async def write_overrides(
    session: AsyncSession, base: PublisherRegistry, entries: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    cleaned = validate_overrides(base, entries)
    row = await session.get(Setting, SETTING_KEY)
    value = {"entries": cleaned}
    if row is None:
        session.add(Setting(key=SETTING_KEY, value=value, updated_at=utcnow()))
    else:
        row.value = value
        row.updated_at = utcnow()
    await session.commit()
    return cleaned


async def affected_cache_entries(
    session: AsyncSession,
    base: PublisherRegistry,
    overrides: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """List cached results whose evidence came from a publisher whose grade changed."""
    changed = diff(base, overrides)
    by_key = {str(entry["key"]): entry for entry in overrides}
    affected_keys = {change["key"] for change in changed}
    names: set[str] = set()
    for shipped in base.entries:
        if str(shipped.get("key")) not in affected_keys:
            continue
        if shipped.get("publisher"):
            names.add(str(shipped["publisher"]).casefold())
        for alias in shipped.get("aliases") or []:
            names.add(str(alias).casefold())
        match = shipped.get("match") or {}
        for alias in match.get("aliases") or []:
            names.add(str(alias).casefold())
    if not names and not by_key:
        return []
    rows = cast(
        list[Any],
        (
            await session.execute(
                select(ClaimCache.id, ClaimCache.result_id, Result.evidence, ClaimCache.created_at)
                .join(Result, Result.id == ClaimCache.result_id)
                .order_by(ClaimCache.created_at.desc())
                .limit(500)
            )
        ).all(),
    )
    affected: list[dict[str, Any]] = []
    for cache_id, result_id, evidence, created_at in rows:
        publishers: set[str] = set()
        for item in evidence or []:
            provenance = item.get("provenance") or {}
            publisher = str(provenance.get("publisher") or "")
            if publisher.casefold() in names:
                publishers.add(publisher)
        if publishers:
            affected.append(
                {
                    "cache_id": cache_id,
                    "result_id": result_id,
                    "created_at": created_at.isoformat(),
                    "publishers": sorted(publishers),
                }
            )
    return affected
