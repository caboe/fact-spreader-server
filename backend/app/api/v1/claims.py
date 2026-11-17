"""Claim archive: all signed-in users see the checked claims (PURPOSE §3.3).

Submitter identities are returned only to the submitter or a caller with `quality:read`;
everyone else sees the claim, the verdict and the evidence, not who asked.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.contracts.api import (
    ArchiveEntry,
    CheckResponse,
    FeedbackRequest,
    JobAccepted,
    RecheckRequest,
)
from app.contracts.enums import TurnType
from app.core.errors import AppError
from app.core.ids import new_id, utcnow
from app.db.models import AuditLog, Feedback, Result
from app.db.models import Job as JobRow
from app.db.session import get_session
from app.services.auth import Principal, current_principal, require_permission
from app.services.checks import create_check_job, job_to_api, load_response

router = APIRouter(prefix="/v1/claims", tags=["claims"])
CurrentPrincipal = Annotated[Principal, Depends(current_principal)]
ClaimsRecheck = Annotated[Principal, Depends(require_permission("claims:recheck"))]
QualityRead = Annotated[Principal, Depends(require_permission("quality:read"))]


def _claim_text(row: Result) -> str:
    statements = row.statements or []
    texts = [
        str(statement.get("text", ""))
        for statement in statements
        if isinstance(statement, dict) and statement.get("checkworthy") and statement.get("text")
    ]
    if texts:
        return " ".join(texts)
    return str((row.input or {}).get("text", ""))[:500]


def _topics(row: Result) -> list[str]:
    topics: list[str] = []
    for statement in row.statements or []:
        for topic in statement.get("topics") or []:
            if isinstance(topic, str) and topic not in topics:
                topics.append(topic)
    return topics


def _entry(row: Result, principal: Principal) -> ArchiveEntry:
    submitted_by = None
    if row.user_id and (row.user_id == principal.user_id or principal.has("quality:read")):
        submitted_by = row.user_id
    return ArchiveEntry(
        result_id=row.id,
        claim_text=_claim_text(row),
        language=row.detected_language,
        overall_verdict=row.overall_verdict,
        topics=_topics(row),
        domain_tags=list(
            {
                tag
                for statement in (row.statements or [])
                for tag in (statement.get("domain_tags") or [])
                if isinstance(tag, str)
            }
        ),
        created_at=row.created_at,
        preliminary=row.preliminary,
        has_contradiction=bool(row.contradictions),
        submitted_by=submitted_by,
    )


@router.get("")
async def list_claims(
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_session)],
    verdict: str | None = None,
    query: str | None = None,
    mine: bool = False,
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    newer = aliased(Result)
    statement = (
        select(Result)
        .where(Result.deleted.is_(False))
        .where(~exists().where(newer.previous_result_id == Result.id))
    )
    if verdict:
        statement = statement.where(Result.overall_verdict == verdict)
    if mine:
        statement = statement.where(Result.user_id == principal.user_id)
    if query:
        statement = statement.where(Result.input["text"].astext.ilike(f"%{query}%"))
    if cursor:
        statement = statement.where(Result.id < cursor)
    rows = (
        (await session.execute(statement.order_by(Result.id.desc()).limit(limit + 1)))
        .scalars()
        .all()
    )
    more = len(rows) > limit
    rows = rows[:limit]
    return {
        "data": [_entry(row, principal).model_dump(mode="json") for row in rows],
        "next_cursor": rows[-1].id if more and rows else None,
    }


async def _version_chain(session: AsyncSession, row: Result) -> list[Result]:
    """Follow the previous-result links in both directions and return version order."""
    chain: dict[str, Result] = {row.id: row}
    current = row
    while current.previous_result_id:
        previous = await session.get(Result, current.previous_result_id)
        if previous is None or previous.id in chain:
            break
        chain[previous.id] = previous
        current = previous
    changed = True
    while changed:
        changed = False
        children = (
            (
                await session.execute(
                    select(Result).where(
                        Result.previous_result_id.in_(list(chain)),
                        Result.deleted.is_(False),
                    )
                )
            )
            .scalars()
            .all()
        )
        for child in children:
            if child.id not in chain:
                chain[child.id] = child
                changed = True
    return sorted(chain.values(), key=lambda item: (item.version, item.created_at))


@router.get("/{result_id}")
async def get_claim(
    result_id: str,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, Any]:
    row = await session.get(Result, result_id)
    if row is None or row.deleted:
        raise AppError(404, "not_found", "The claim does not exist.")
    versions = await _version_chain(session, row)
    current = versions[-1]
    response: CheckResponse | None = await load_response(session, current.id)
    if response is None:
        raise AppError(404, "not_found", "The claim does not exist.")
    feedback_rows = (
        (await session.execute(select(Feedback).where(Feedback.result_id == current.id)))
        .scalars()
        .all()
    )
    counts = {"helpful": 0, "unhelpful": 0, "incorrect": 0}
    my_feedback = None
    for feedback in feedback_rows:
        if feedback.kind in counts:
            counts[feedback.kind] += 1
        if feedback.user_id == principal.user_id:
            my_feedback = feedback.kind
    submitted_by = None
    if current.user_id and (current.user_id == principal.user_id or principal.has("quality:read")):
        submitted_by = current.user_id
    return {
        "result": response.model_dump(mode="json", by_alias=True),
        "versions": [
            {
                "result_id": item.id,
                "version": item.version,
                "created_at": item.created_at.isoformat(),
                "preliminary": item.preliminary,
                "current": item.id == current.id,
            }
            for item in versions
        ],
        "feedback": {**counts, "my_feedback": my_feedback},
        "submitted_by": submitted_by,
    }


@router.post("/{result_id}/feedback", status_code=204)
async def submit_feedback(
    result_id: str,
    body: FeedbackRequest,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    result = await session.get(Result, result_id)
    if result is None or result.deleted:
        raise AppError(404, "not_found", "The claim does not exist.")
    existing = (
        await session.execute(
            select(Feedback).where(
                Feedback.result_id == result_id, Feedback.user_id == principal.user_id
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        session.add(
            Feedback(
                id=new_id("fbk"),
                result_id=result_id,
                user_id=principal.user_id,
                kind=body.kind,
                comment=body.comment,
                created_at=utcnow(),
            )
        )
    else:
        existing.kind = body.kind
        existing.comment = body.comment
        existing.created_at = utcnow()
    await session.commit()


@router.post("/{result_id}/recheck", status_code=202)
async def recheck_claim(
    result_id: str,
    body: RecheckRequest,
    request: Request,
    principal: ClaimsRecheck,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, Any]:
    row = await session.get(Result, result_id)
    if row is None or row.deleted:
        raise AppError(404, "not_found", "The claim does not exist.")
    versions = await _version_chain(session, row)
    current = versions[-1]
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    used = (
        await session.execute(
            select(func.count(JobRow.id)).where(
                JobRow.created_at >= today,
                JobRow.payload["recheck"].astext == "true",
            )
        )
    ).scalar_one()
    if int(used) >= request.app.state.settings.recheck_daily_budget:
        raise AppError(429, "budget_exceeded", "The daily re-check budget is exhausted.")
    input_info = current.input or {}
    text = str(input_info.get("text") or "")
    if not text:
        raise AppError(422, "invalid_input", "The stored claim has no text to re-check.")
    job, _moderation = await create_check_job(
        session,
        settings=request.app.state.settings,
        publishers=request.app.state.publishers,
        methodology=request.app.state.methodology,
        text=text,
        user_id=principal.user_id,
        response_language=current.response_language,
        turn_type=TurnType(current.turn_type),
        source_url=input_info.get("url"),
        source_file_name=input_info.get("file_name"),
        source_media_type=input_info.get("media_type"),
        source_size_bytes=input_info.get("size_bytes"),
        context=(input_info.get("context") or {}).get("messages"),
        previous_result_id=current.id,
    )
    job.payload = {
        **(job.payload or {}),
        "recheck": True,
        "recheck_reason": body.reason,
        "fast": body.fast,
    }
    await session.commit()
    api_job = job_to_api(job)
    return JobAccepted(job=api_job, poll_after_ms=api_job.poll_after_ms).model_dump(mode="json")


@router.delete("/{result_id}", status_code=204)
async def delete_claim(
    result_id: str,
    principal: QualityRead,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    row = await session.get(Result, result_id)
    if row is None or row.deleted:
        raise AppError(404, "not_found", "The claim does not exist.")
    versions = await _version_chain(session, row)
    for item in versions:
        item.deleted = True
    session.add(
        AuditLog(
            id=new_id("aud"),
            actor_id=principal.user_id,
            actor_type="user",
            action="claim_deleted",
            object_type="result",
            object_id=versions[-1].id,
            detail={"versions": [item.id for item in versions]},
            created_at=utcnow(),
        )
    )
    await session.commit()
