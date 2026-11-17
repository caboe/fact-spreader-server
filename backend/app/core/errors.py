"""RFC 9457 problem responses and application error types (PROTOCOL §1)."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

PROBLEM_BASE = "https://fact-spreader.org/problems/"


class AppError(Exception):
    """An expected, client-visible failure. Never contains secrets or prompt text."""

    def __init__(
        self,
        status: int,
        code: str,
        detail: str,
        *,
        title: str | None = None,
        headers: dict[str, str] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(detail)
        self.status = status
        self.code = code
        self.detail = detail
        self.title = title or code.replace("_", " ").capitalize()
        self.headers = headers or {}
        self.extra = extra or {}


def problem(
    status: int,
    code: str,
    detail: str,
    *,
    title: str | None = None,
    instance: str | None = None,
    headers: dict[str, str] | None = None,
    extra: dict[str, Any] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": f"{PROBLEM_BASE}{code}",
        "title": title or code.replace("_", " ").capitalize(),
        "status": status,
        "detail": detail,
        "code": code,
    }
    if instance:
        body["instance"] = instance
    if extra:
        body.update(extra)
    return JSONResponse(
        status_code=status,
        content=body,
        media_type="application/problem+json",
        headers=headers,
    )


async def app_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    return problem(
        exc.status,
        exc.code,
        exc.detail,
        title=exc.title,
        instance=str(request.url.path),
        headers=exc.headers,
        extra=exc.extra,
    )


def not_found(what: str = "resource") -> AppError:
    return AppError(404, "not_found", f"The {what} does not exist.")


def permission_denied(detail: str = "The credential lacks the required permission.") -> AppError:
    return AppError(403, "permission_denied", detail)
