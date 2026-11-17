"""Claim archive: all signed-in users see the checked claims (PURPOSE §3.3).

Submitter identities are returned only to the submitter or a caller with `quality:read`;
everyone else sees the claim, the verdict and the evidence, not who asked.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.api import ArchiveEntry, CheckResponse, FeedbackRequest
from app.core.errors import AppError
from app.core.ids import new_id, utcnow
from app.db.models import Feedback, Result
from app.db.session import get_session
from app.services.auth import Principal, current_principal
from app.services.checks import load_response

router = APIRouter(prefix="/v1/claims", tags=["claims"])
CurrentPrincipal = Annotated[Principal, Depends(current_principal)]


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
    statement = select(Result).where(Result.deleted.is_(False))
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


@router.get("/{result_id}")
async def get_claim(
    result_id: str,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, Any]:
    row = await session.get(Result, result_id)
    if row is None or row.deleted:
        raise AppError(404, "not_found", "The claim does not exist.")
    response: CheckResponse | None = await load_response(session, result_id)
    if response is None:
        raise AppError(404, "not_found", "The claim does not exist.")
    feedback_rows = (
        (await session.execute(select(Feedback).where(Feedback.result_id == result_id)))
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
    if row.user_id and (row.user_id == principal.user_id or principal.has("quality:read")):
        submitted_by = row.user_id
    return {
        "result": response.model_dump(mode="json", by_alias=True),
        "versions": [
            {
                "result_id": row.id,
                "version": row.version,
                "created_at": row.created_at.isoformat(),
                "preliminary": row.preliminary,
                "current": True,
            }
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
