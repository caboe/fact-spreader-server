"""OpenAI-shaped model list. Phase 1 exposes the deterministic substance entry only."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.contracts.api import OpenAIModelCard, OpenAIModelList
from app.services.auth import Principal, require_permission

router = APIRouter(prefix="/v1", tags=["models"])
ClaimsSubmit = Annotated[Principal, Depends(require_permission("claims:submit"))]


@router.get("/models", response_model=OpenAIModelList)
async def list_models(principal: ClaimsSubmit) -> OpenAIModelList:
    return OpenAIModelList(
        data=[
            OpenAIModelCard(
                id="factcheck:none",
                created=1763334000,
                factcheck={
                    "kind": "substance",
                    "persona_id": None,
                    "output_formats": ["substance", "compact"],
                    "fast": False,
                    "streaming": False,
                },
            )
        ]
    )
