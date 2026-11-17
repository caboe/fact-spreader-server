"""Editor lists for contradictions and corpus gaps (PROTOCOL §9)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.api import (
    EditorContradiction,
    EditorGap,
    EditorStateRequest,
    GapRecheckRequest,
)
from app.contracts.enums import TurnType
from app.core.errors import AppError
from app.db.models import ContradictionRecord, CorpusGap, Result
from app.db.models import Job as JobRow
from app.db.session import get_session
from app.services.auth import Principal, require_permission
from app.services.checks import create_check_job, job_to_api

router = APIRouter(prefix="/v1/editor", tags=["editor"])
EditorRead = Annotated[
    Principal,
    Depends(require_permission("documents:review")),
]

_CONTRADICTION_STATES = {"open", "acknowledged", "resolved"}
_GAP_STATES = {"open", "linked", "dismissed"}


@router.get("/contradictions")
async def list_contradictions(
    principal: EditorRead,
    session: Annotated[AsyncSession, Depends(get_session)],
    state: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    statement = select(ContradictionRecord).order_by(ContradictionRecord.detected_at.desc())
    if state:
        statement = statement.where(ContradictionRecord.state == state)
    rows = (await session.execute(statement.limit(limit))).scalars().all()
    data = [
        EditorContradiction(
            id=row.id,
            statement_text=row.statement_text,
            result_ids=list(row.result_ids or []),
            supporting=list(row.supporting or []),
            refuting=list(row.refuting or []),
            state=row.state,
            detected_at=row.detected_at,
        ).model_dump(mode="json")
        for row in rows
    ]
    return {
        "data": data,
        "counts": {"total": len(data), "open": sum(1 for r in rows if r.state == "open")},
    }


@router.patch("/contradictions/{record_id}")
async def update_contradiction(
    record_id: str,
    body: EditorStateRequest,
    principal: EditorRead,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, Any]:
    if body.state not in _CONTRADICTION_STATES - {"open"}:
        raise AppError(422, "invalid_state", "The state must be acknowledged or resolved.")
    row = await session.get(ContradictionRecord, record_id)
    if row is None:
        raise AppError(404, "not_found", "The contradiction does not exist.")
    row.state = body.state
    await session.commit()
    return {"id": row.id, "state": row.state}


@router.get("/gaps")
async def list_gaps(
    principal: EditorRead,
    session: Annotated[AsyncSession, Depends(get_session)],
    state: str | None = None,
    sort: str = "frequency",
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    statement = select(CorpusGap)
    if state:
        statement = statement.where(CorpusGap.state == state)
    order = CorpusGap.last_seen.desc() if sort == "last_seen" else CorpusGap.frequency.desc()
    rows = (await session.execute(statement.order_by(order).limit(limit))).scalars().all()
    data = [
        EditorGap(
            id=row.id,
            normalized_topic=row.normalized_topic,
            query=row.query,
            language=row.language,
            topics=list(row.topics or []),
            frequency=row.frequency,
            sample_result_ids=list(row.sample_result_ids or []),
            state=row.state,
            first_seen=row.first_seen,
            last_seen=row.last_seen,
        ).model_dump(mode="json")
        for row in rows
    ]
    return {
        "data": data,
        "counts": {"total": len(data), "open": sum(1 for r in rows if r.state == "open")},
    }


@router.patch("/gaps/{gap_id}")
async def update_gap(
    gap_id: str,
    body: EditorStateRequest,
    principal: EditorRead,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, Any]:
    if body.state not in _GAP_STATES - {"open"}:
        raise AppError(422, "invalid_state", "The state must be linked or dismissed.")
    row = await session.get(CorpusGap, gap_id)
    if row is None:
        raise AppError(404, "not_found", "The gap does not exist.")
    row.state = body.state
    await session.commit()
    return {"id": row.id, "state": row.state}


@router.post("/gaps/{gap_id}/recheck", status_code=202)
async def recheck_gap(
    gap_id: str,
    body: GapRecheckRequest,
    request: Request,
    principal: EditorRead,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, Any]:
    gap = await session.get(CorpusGap, gap_id)
    if gap is None:
        raise AppError(404, "not_found", "The gap does not exist.")
    today = (
        __import__("datetime")
        .datetime.now(__import__("datetime").UTC)
        .replace(hour=0, minute=0, second=0, microsecond=0)
    )
    used = int(
        (
            await session.execute(
                select(func.count(JobRow.id)).where(
                    JobRow.created_at >= today,
                    JobRow.payload["recheck"].astext == "true",
                )
            )
        ).scalar_one()
    )
    remaining = max(0, request.app.state.settings.recheck_daily_budget - used)
    jobs: list[dict[str, Any]] = []
    skipped = 0
    for result_id in (gap.sample_result_ids or [])[: body.limit]:
        row = await session.get(Result, str(result_id))
        if row is None or row.deleted:
            continue
        if len(jobs) >= remaining:
            skipped += 1
            continue
        text = str((row.input or {}).get("text") or "").strip()
        if not text:
            continue
        job, _moderation = await create_check_job(
            session,
            settings=request.app.state.settings,
            publishers=request.app.state.publishers,
            methodology=request.app.state.methodology,
            text=text,
            user_id=principal.user_id,
            response_language=row.response_language,
            turn_type=TurnType(row.turn_type),
            source_url=(row.input or {}).get("url"),
            source_file_name=(row.input or {}).get("file_name"),
            source_media_type=(row.input or {}).get("media_type"),
            source_size_bytes=(row.input or {}).get("size_bytes"),
            previous_result_id=row.id,
        )
        job.payload = {
            **(job.payload or {}),
            "recheck": True,
            "recheck_reason": "gap",
            "recheck_gap_id": gap.id,
        }
        jobs.append(job_to_api(job).model_dump(mode="json"))
    await session.commit()
    return {"jobs": jobs, "skipped_budget": skipped}
