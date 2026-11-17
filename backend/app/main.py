"""FastAPI application factory and ASGI entrypoint (PROTOCOL §1, IMPLEMENT Phase 1)."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import redis.asyncio as redis
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.internal.llm import _InternalAuthError
from app.api.internal.llm import router as internal_llm_router
from app.api.v1.checks import router as checks_router
from app.api.v1.claims import router as claims_router
from app.api.v1.devices import router as devices_router
from app.api.v1.documents import router as documents_router
from app.api.v1.health import router as health_router
from app.api.v1.instance import router as instance_router
from app.api.v1.openai import OpenAIAuthError
from app.api.v1.openai import router as openai_router
from app.api.v1.research import router as research_router
from app.api.v1.usage import router as usage_router
from app.api.web.auth import router as auth_router
from app.core.config import Settings, get_settings
from app.core.errors import AppError, app_error_handler, problem
from app.core.logging import RequestContextMiddleware, configure_logging
from app.db.session import Database
from app.retrieval.lightrag import LightRAGClient
from app.services.language import LanguageService
from app.services.methodology import Methodology
from app.services.personas import PersonaRegistry
from app.services.publishers import PublisherRegistry

logger = logging.getLogger("app.main")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        database = Database(settings)
        cache = redis.from_url(  # type: ignore[no-untyped-call]
            settings.redis_url, encoding="utf-8", decode_responses=True
        )
        app.state.settings = settings
        app.state.db = database
        app.state.redis = cache
        app.state.publishers = PublisherRegistry.from_path(settings.publisher_list_path)
        app.state.personas = PersonaRegistry.from_path(settings.personas_path)
        app.state.methodology = Methodology.load(settings.checklist_dir, settings.pattern_list_path)
        app.state.language = LanguageService(
            settings.supported_languages, settings.default_response_language
        )
        app.state.lightrag = LightRAGClient(settings)
        logger.info("application_started", extra={"event": "startup"})
        try:
            yield
        finally:
            await database.dispose()
            await cache.aclose()
            logger.info("application_stopped", extra={"event": "shutdown"})

    app = FastAPI(
        title="Fact Spreader",
        version="0.1.0",
        description=(
            "Fact-check and research service over an editorially approved corpus. "
            "Phase 1 exposes the check pipeline, jobs and the internal LLM gateway."
        ),
        lifespan=lifespan,
        docs_url="/docs" if settings.app_env != "production" else None,
        redoc_url=None,
        openapi_url="/openapi.json",
    )
    app.add_middleware(RequestContextMiddleware)
    if settings.cors_extension_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_extension_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "X-CSRF-Token", "Idempotency-Key"],
            expose_headers=["ETag", "X-Request-Id", "RateLimit-Limit", "RateLimit-Remaining"],
        )

    app.add_exception_handler(AppError, app_error_handler)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, RequestValidationError)
        return problem(
            422,
            "validation_error",
            "The request body is invalid.",
            instance=str(request.url.path),
            extra={"errors": jsonable_encoder(exc.errors())},
        )

    @app.exception_handler(OpenAIAuthError)
    async def openai_auth_handler(request: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, OpenAIAuthError)
        return JSONResponse(
            status_code=exc.status,
            content={
                "error": {
                    "message": exc.message,
                    "type": "authentication_error",
                    "code": exc.code,
                    "param": None,
                }
            },
        )

    @app.exception_handler(_InternalAuthError)
    async def internal_auth_handler(request: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, _InternalAuthError)
        return JSONResponse(
            status_code=exc.status,
            content={
                "error": {
                    "message": "The internal gateway credential is missing or invalid.",
                    "type": "authentication_error",
                    "code": exc.code,
                    "param": None,
                }
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_exception", extra={"route": request.url.path})
        return problem(
            500,
            "internal_error",
            "The request failed unexpectedly.",
            instance=str(request.url.path),
        )

    app.include_router(health_router)
    app.include_router(instance_router)
    app.include_router(checks_router)
    app.include_router(claims_router)
    app.include_router(devices_router)
    app.include_router(documents_router)
    app.include_router(openai_router)
    app.include_router(research_router)
    app.include_router(usage_router)
    app.include_router(auth_router)
    app.include_router(internal_llm_router, include_in_schema=False)
    return app


app = create_app()
