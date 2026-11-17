"""Local methodology overrides for patterns and confounder checklists (Phase 6).

The shipped JSON files remain the baseline; an override changes an existing pattern's
wording or a checklist's staleness window and confounder hints. New patterns and topics
are not accepted from this API: they change what the model looks for and need a reviewed
file change. Every write bumps a local version that is mixed into the pattern version, so
cached config hashes change.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.ids import utcnow
from app.db.models import Setting
from app.services.methodology import Confounder, Methodology

SETTING_KEY = "methodology.overrides"


def _parse(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {"version": 0, "patterns": {}, "checklists": {}}
    return {
        "version": int(raw.get("version", 0)),
        "patterns": dict(raw.get("patterns") or {}),
        "checklists": dict(raw.get("checklists") or {}),
    }


async def load_overrides(session: AsyncSession) -> dict[str, Any]:
    row = await session.get(Setting, SETTING_KEY)
    return _parse(row.value if row is not None else None)


def version_tag(overrides: dict[str, Any]) -> str:
    if not overrides.get("patterns") and not overrides.get("checklists"):
        return ""
    digest = hashlib.sha256(
        json.dumps(overrides, sort_keys=True, default=str).encode()
    ).hexdigest()[:8]
    return f"+local.{overrides.get('version', 0)}.{digest}"


def effective_methodology(base: Methodology, overrides: dict[str, Any]) -> Methodology:
    tag = version_tag(overrides)
    patterns = {pattern_id: dict(value) for pattern_id, value in base.patterns.items()}
    for pattern_id, change in (overrides.get("patterns") or {}).items():
        if pattern_id in patterns and isinstance(change, dict):
            patterns[pattern_id] = {**patterns[pattern_id], **change}
    checklists = {}
    for topic, checklist in base.checklists.items():
        change = (overrides.get("checklists") or {}).get(topic) or {}
        staleness_days = int(change.get("staleness_days", checklist.staleness_days))
        confounders = {confounder.id: confounder for confounder in checklist.confounders}
        for item in change.get("confounders") or []:
            if not isinstance(item, dict):
                continue
            confounder_id = str(item.get("id") or "")
            if not confounder_id:
                continue
            existing = confounders.get(confounder_id)
            confounders[confounder_id] = Confounder(
                id=confounder_id,
                label=str(item.get("label", existing.label if existing else confounder_id)),
                retrieval_hint=str(
                    item.get("retrieval_hint", existing.retrieval_hint if existing else "")
                ),
                retrieval_hint_de=item.get(
                    "retrieval_hint_de",
                    existing.retrieval_hint_de if existing else None,
                ),
            )
        checklists[topic] = replace(
            checklist,
            version=f"{checklist.version}{tag}",
            staleness_days=staleness_days,
            confounders=tuple(confounders.values()),
        )
    return Methodology(
        checklists=checklists,
        patterns=patterns,
        patterns_version=f"{base.patterns_version}{tag}",
    )


async def effective_methodology_for(
    session: AsyncSession, checklist_dir: str, pattern_path: str
) -> Methodology:
    return effective_methodology(
        Methodology.load(checklist_dir, pattern_path), await load_overrides(session)
    )


async def _write(session: AsyncSession, overrides: dict[str, Any], *, actor_id: str | None) -> None:
    from app.core.ids import new_id
    from app.db.models import AuditLog

    overrides["version"] = int(overrides.get("version", 0)) + 1
    row = await session.get(Setting, SETTING_KEY)
    if row is None:
        session.add(Setting(key=SETTING_KEY, value=overrides, updated_at=utcnow()))
    else:
        row.value = overrides
        row.updated_at = utcnow()
    session.add(
        AuditLog(
            id=new_id("aud"),
            actor_id=actor_id,
            actor_type="user" if actor_id else "system",
            action="methodology_override_written",
            object_type="methodology",
            object_id=None,
            detail={"version": overrides["version"]},
            created_at=utcnow(),
        )
    )
    await session.commit()


async def write_pattern(
    session: AsyncSession,
    base: Methodology,
    pattern_id: str,
    fields: dict[str, Any],
    *,
    actor_id: str | None,
) -> None:
    if pattern_id not in base.patterns:
        raise AppError(422, "unknown_pattern", f"Unknown pattern {pattern_id!r}.")
    allowed = {
        key: value for key, value in fields.items() if key in {"name", "definition", "mechanism"}
    }
    if not allowed:
        raise AppError(422, "empty_override", "Provide name, definition or mechanism.")
    overrides = await load_overrides(session)
    overrides["patterns"][pattern_id] = {
        **(overrides["patterns"].get(pattern_id) or {}),
        **{key: str(value)[:4000] for key, value in allowed.items()},
    }
    await _write(session, overrides, actor_id=actor_id)


async def write_checklist(
    session: AsyncSession,
    base: Methodology,
    topic: str,
    fields: dict[str, Any],
    *,
    actor_id: str | None,
) -> None:
    if topic not in base.checklists:
        raise AppError(422, "unknown_topic", f"Unknown checklist topic {topic!r}.")
    change: dict[str, Any] = {}
    if fields.get("staleness_days") is not None:
        days = int(fields["staleness_days"])
        if not 30 <= days <= 3650:
            raise AppError(422, "invalid_staleness", "staleness_days must be 30..3650.")
        change["staleness_days"] = days
    if fields.get("confounders") is not None:
        known = {confounder.id for confounder in base.checklists[topic].confounders}
        items = []
        for item in fields["confounders"]:
            confounder_id = str(item.get("id") or "")
            if confounder_id not in known:
                raise AppError(422, "unknown_confounder", f"Unknown confounder {confounder_id!r}.")
            cleaned = {"id": confounder_id}
            for key in ("label", "retrieval_hint", "retrieval_hint_de"):
                if item.get(key) is not None:
                    cleaned[key] = str(item[key])[:500]
            items.append(cleaned)
        change["confounders"] = items
    if not change:
        raise AppError(422, "empty_override", "Provide staleness_days or confounders.")
    overrides = await load_overrides(session)
    stored = overrides["checklists"].get(topic) or {}
    if "confounders" in change:
        merged = {item["id"]: item for item in stored.get("confounders", [])}
        for item in change["confounders"]:
            merged[item["id"]] = {**merged.get(item["id"], {}), **item}
        change["confounders"] = list(merged.values())
    overrides["checklists"][topic] = {**stored, **change}
    await _write(session, overrides, actor_id=actor_id)
