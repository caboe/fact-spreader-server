"""Structured JSON logging with a request id and no content.

Logs carry route, status, latency, principal ids and usage figures. They never carry
prompts, claim text, documents, evidence or secrets (PROTOCOL §14).
"""

from __future__ import annotations

import json
import logging
import sys
import time
import uuid
from contextvars import ContextVar
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

request_id_ctx: ContextVar[str] = ContextVar("request_id", default="")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_ctx.get(),
        }
        for key in ("route", "method", "status", "latency_ms", "principal_id", "event"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
    # httpx logs URLs and sometimes headers at INFO; keep it quiet.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attach a request id, emit one completion line and never log bodies."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("X-Request-Id") or f"req_{uuid.uuid4().hex}"
        token = request_id_ctx.set(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logging.getLogger("app.request").exception(
                "request_failed",
                extra={"route": request.url.path, "method": request.method, "status": 500},
            )
            raise
        finally:
            request_id_ctx.reset(token)
        response.headers["X-Request-Id"] = request_id
        logging.getLogger("app.request").info(
            "request_completed",
            extra={
                "route": request.url.path,
                "method": request.method,
                "status": response.status_code,
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            },
        )
        return response
