"""Raw retrieval endpoint: LightRAG passages without a fact check (PROTOCOL §5.3)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.api import RawRetrievalRequest, RawRetrievalResponse
from app.core.errors import AppError
from app.db.session import get_session
from app.retrieval.lightrag import LightRAGError
from app.services.auth import Principal, require_permission
from app.services.raw_retrieval import RawRetrievalService
from app.services.setup import setup_gate_dependency

router = APIRouter(prefix="/v1", tags=["retrieval"])
SearchUse = Annotated[Principal, Depends(require_permission("search:use"))]


@router.post("/retrieval", response_model=RawRetrievalResponse)
async def retrieval(
    request: Request,
    body: RawRetrievalRequest,
    principal: SearchUse,
    session: Annotated[AsyncSession, Depends(get_session)],
    _setup: Annotated[None, Depends(setup_gate_dependency)] = None,
) -> RawRetrievalResponse:
    settings = request.app.state.settings
    service = RawRetrievalService(
        session=session,
        lightrag=request.app.state.lightrag,
    )
    try:
        return await service.retrieve(
            query=body.query,
            mode=body.mode,
            top_k=body.top_k or settings.lightrag_top_k,
            chunk_top_k=body.chunk_top_k or settings.lightrag_chunk_top_k,
            include_graph=body.include_graph,
        )
    except LightRAGError as exc:
        raise AppError(
            503,
            "retrieval_unavailable",
            "The raw retrieval service is unavailable.",
        ) from exc
