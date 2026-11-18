"""Worker queue ordering (IMPLEMENT Phase 1/4).

A URL batch creates one `document_index` job per file. A user's check must not wait
behind all of them; the worker claims interactive checks first.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from app.core.config import Settings
from app.core.ids import new_id, utcnow
from app.db.models import Job as JobRow
from app.db.session import Database
from app.worker import claim_job

pytestmark = pytest.mark.integration


async def test_a_check_is_claimed_before_an_older_document_index_job(
    app: Any, settings: Settings
) -> None:
    database = Database(settings)
    try:
        async with database.session_factory() as session:
            session.add_all(
                [
                    JobRow(
                        id=new_id("job"),
                        kind="document_index",
                        state="queued",
                        payload={},
                        progress=0.0,
                        attempts=0,
                        created_at=utcnow() - timedelta(minutes=5),
                    ),
                    JobRow(
                        id=new_id("job"),
                        kind="check",
                        state="queued",
                        payload={},
                        progress=0.0,
                        attempts=0,
                        created_at=utcnow(),
                    ),
                ]
            )
            await session.commit()
            first = await claim_job(session, "worker:test")
            assert first is not None
            assert first.kind == "check"
            second = await claim_job(session, "worker:test")
            assert second is not None
            assert second.kind == "document_index"
    finally:
        await database.dispose()
