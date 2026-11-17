"""Public instance identity (PROTOCOL §3.1)."""

from __future__ import annotations

from fastapi import APIRouter, Request
from sqlalchemy import func, select

from app.contracts.api import InstanceInfo
from app.core.errors import AppError
from app.db.models import Document, Instance

router = APIRouter(tags=["instance"])


@router.get("/v1/instance", response_model=InstanceInfo)
async def instance_info(request: Request) -> InstanceInfo:
    async with request.app.state.db.session_factory() as session:
        instance = (await session.execute(select(Instance).limit(1))).scalar_one_or_none()
        if instance is None:
            raise AppError(
                503,
                "setup_required",
                "The instance has not been initialised yet.",
            )
        document_count = (
            await session.execute(
                select(func.count(Document.id)).where(
                    Document.deleted.is_(False), Document.state.in_(["approved", "indexed"])
                )
            )
        ).scalar_one()
    settings = request.app.state.settings
    return InstanceInfo(
        instance_id=instance.id,
        name=instance.name,
        organization=instance.organization if instance.overview_public else None,
        contact=instance.contact if instance.overview_public else None,
        setup_complete=instance.setup_complete,
        capabilities=["check"],
        corpus_version=instance.corpus_version,
        document_count=int(document_count),
        supported_response_languages=list(settings.supported_languages),
        supported_corpus_languages=list(settings.supported_languages),
        languages=list(settings.supported_languages),
        features={"fast_mode": False, "research_summary": False, "vision": False},
    )
