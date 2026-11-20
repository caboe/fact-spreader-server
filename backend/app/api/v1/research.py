"""Research endpoint: documents, passages and archive hits (PROTOCOL §5)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.api import ResearchRequest, ResearchResponse
from app.core.errors import AppError
from app.db.session import get_session
from app.llm.client import LLMClient, LLMError
from app.retrieval.lightrag import LightRAGError
from app.retrieval.relevance import build_retriever
from app.services.auth import Principal, require_permission
from app.services.language import LanguageService
from app.services.research import ResearchService
from app.services.setup import setup_gate_dependency

router = APIRouter(prefix="/v1", tags=["research"])
SearchUse = Annotated[Principal, Depends(require_permission("search:use"))]


@router.post("/search", response_model=ResearchResponse)
async def search(
    request: Request,
    body: ResearchRequest,
    principal: SearchUse,
    session: Annotated[AsyncSession, Depends(get_session)],
    _setup: Annotated[None, Depends(setup_gate_dependency)] = None,
) -> ResearchResponse:
    languages: LanguageService = request.app.state.language
    decision = languages.resolve(body.query, body.response_language)
    settings = request.app.state.settings
    service = ResearchService(
        session=session,
        retriever=build_retriever(
            settings,
            lightrag=request.app.state.lightrag,
            embedder=request.app.state.embedder,
            engine=request.app.state.db.engine,
        ),
        llm=LLMClient(settings, consumer="research"),
    )
    try:
        return await service.search(
            query=body.query,
            response_language=decision.response,
            filters=body.filters,
            summary=body.summary,
            limit=body.limit,
            summary_timeout_seconds=settings.research_summary_timeout_seconds,
        )
    except (LightRAGError, LLMError) as exc:
        raise AppError(
            503, "retrieval_unavailable", "The retrieval service is unavailable."
        ) from exc
