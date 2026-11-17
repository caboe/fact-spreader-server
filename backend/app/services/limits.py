"""Per-user limits enforced before model work starts (IMPLEMENT Phase 5)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import Job, User


def _limit(user: User, field: str, default: int) -> int:
    value = getattr(user, field)
    return int(value) if value is not None else default


async def enforce_limits(
    session: AsyncSession,
    settings: Settings,
    user_id: str,
    *,
    text_chars: int | None = None,
    file_bytes: int | None = None,
    batch_files: int | None = None,
) -> None:
    if user_id.startswith("usr_"):
        user = await session.get(User, user_id)
        if user is not None:
            if text_chars is not None and text_chars > _limit(
                user, "text_chars", settings.user_text_chars
            ):
                raise AppError(
                    413, "payload_too_large", "The input exceeds this user's text limit."
                )
            if file_bytes is not None and file_bytes > _limit(
                user, "max_file_bytes", settings.user_max_file_bytes
            ):
                raise AppError(413, "payload_too_large", "The file exceeds this user's size limit.")
            if batch_files is not None and batch_files > _limit(
                user, "max_batch_files", settings.user_max_batch_files
            ):
                raise AppError(413, "payload_too_large", "This user's batch file limit is lower.")
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    used = int(
        (
            await session.execute(
                select(func.count(Job.id)).where(Job.user_id == user_id, Job.created_at >= today)
            )
        ).scalar_one()
    )
    user = await session.get(User, user_id)
    if user is None:
        return
    if used >= _limit(user, "requests_per_day", settings.requests_per_day):
        raise AppError(
            429,
            "rate_limit_exceeded",
            "This user's daily request limit is exhausted.",
        )
