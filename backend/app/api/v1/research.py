"""Research endpoint: documents, passages and archive hits (PROTOCOL §5)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.api import ResearchRequest, ResearchResponse
from app.db.session import get_session
from app.services.auth import Principal, require_permission
from app.services.language import LanguageService
from app.services.research import ResearchService

router = APIRouter(prefix="/v1", tags=["research"])
SearchUse = Annotated[Principal, Depends(require_permission("search:use"))]


@router.post("/search", response_model=ResearchResponse)
async def search(
    request: Request,
    body: ResearchRequest,
    principal: SearchUse,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ResearchResponse:
    languages: LanguageService = request.app.state.language
    decision = languages.resolve(body.query, body.response_language)
    service = ResearchService(session=session, lightrag=request.app.state.lightrag)
    return await service.search(
        query=body.query,
        response_language=decision.response,
        filters=body.filters,
        summary=body.summary,
        limit=body.limit,
    )
