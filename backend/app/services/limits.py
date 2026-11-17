"""Per-user and per-API-key limits enforced before model work starts (IMPLEMENT Phase 5).

A credential never gets more than its owner. A key may tighten the four limits; the
effective value is the minimum of the user's limit, the key's limit and the deployment
default. Daily request counting is per user because the gateway and the job rows attribute
work to the user; a lower key ceiling therefore still caps the user's shared daily budget.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import ApiKey, Job, User
from app.services.auth import Principal

LIMIT_FIELDS = ("requests_per_day", "text_chars", "max_file_bytes", "max_batch_files")


def _effective_limit(user: User, key: ApiKey | None, field: str, default: int) -> int:
    values = [int(getattr(user, field)) if getattr(user, field) is not None else int(default)]
    if key is not None and getattr(key, field) is not None:
        values.append(int(getattr(key, field)))
    return min(values)


async def enforce_limits(
    session: AsyncSession,
    settings: Settings,
    principal: Principal,
    *,
    text_chars: int | None = None,
    file_bytes: int | None = None,
    batch_files: int | None = None,
) -> None:
    user = await session.get(User, principal.user_id)
    if user is None:
        return
    key = await session.get(ApiKey, principal.api_key_id) if principal.api_key_id else None
    if text_chars is not None and text_chars > _effective_limit(
        user, key, "text_chars", settings.user_text_chars
    ):
        raise AppError(413, "payload_too_large", "The input exceeds this credential's text limit.")
    if file_bytes is not None and file_bytes > _effective_limit(
        user, key, "max_file_bytes", settings.user_max_file_bytes
    ):
        raise AppError(413, "payload_too_large", "The file exceeds this credential's size limit.")
    if batch_files is not None and batch_files > _effective_limit(
        user, key, "max_batch_files", settings.user_max_batch_files
    ):
        raise AppError(413, "payload_too_large", "This credential's batch file limit is lower.")
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    used = int(
        (
            await session.execute(
                select(func.count(Job.id)).where(
                    Job.user_id == principal.user_id, Job.created_at >= today
                )
            )
        ).scalar_one()
    )
    if used >= _effective_limit(user, key, "requests_per_day", settings.requests_per_day):
        raise AppError(
            429,
            "rate_limit_exceeded",
            "This credential's daily request limit is exhausted.",
        )
