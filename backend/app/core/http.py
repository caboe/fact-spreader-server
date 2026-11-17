"""Outbound HTTP with a timeout, a retry budget and a circuit breaker.

Hard invariant 14 applies to every outbound call. The breaker is in-process for Phase 1;
a shared breaker can move to Redis when the backend is replicated.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

import httpx


class CircuitOpenError(RuntimeError):
    pass


@dataclass
class CircuitBreaker:
    failure_threshold: int = 5
    cooldown_seconds: float = 30.0
    failures: int = 0
    opened_at: float | None = None
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    async def allow(self) -> None:
        async with self._lock:
            if self.opened_at is None:
                return
            if time.monotonic() - self.opened_at >= self.cooldown_seconds:
                self.opened_at = None
                self.failures = 0
                return
            raise CircuitOpenError("circuit breaker is open")

    async def record_success(self) -> None:
        async with self._lock:
            self.failures = 0
            self.opened_at = None

    async def record_failure(self) -> None:
        async with self._lock:
            self.failures += 1
            if self.failures >= self.failure_threshold:
                self.opened_at = time.monotonic()


class OutboundHTTP:
    """Small wrapper used by the LightRAG client and the LLM client.

    Retries are deliberately bounded: a failed pipeline call gets at most one retry after
    a short backoff. Non-idempotent calls (POST) are only retried on connection errors and
    5xx responses, and the gateway/lightrag endpoints are idempotent enough for that.
    """

    def __init__(
        self,
        *,
        timeout: float = 30.0,
        retries: int = 1,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._timeout = timeout
        self._retries = retries
        self._transport = transport
        self._breakers: dict[str, CircuitBreaker] = {}

    def breaker_for(self, base_url: str) -> CircuitBreaker:
        key = base_url.rstrip("/")
        if key not in self._breakers:
            self._breakers[key] = CircuitBreaker()
        return self._breakers[key]

    async def request(
        self,
        method: str,
        url: str,
        *,
        json: Any = None,
        headers: dict[str, str] | None = None,
        request_timeout: float | None = None,
    ) -> httpx.Response:
        origin = str(httpx.URL(url).copy_with(path="", query=b""))
        breaker = self.breaker_for(origin)
        await breaker.allow()
        attempt = 0
        last_error: Exception | None = None
        while attempt <= self._retries:
            try:
                async with httpx.AsyncClient(
                    timeout=request_timeout or self._timeout,
                    transport=self._transport,
                    follow_redirects=False,
                ) as client:
                    response = await client.request(method, url, json=json, headers=headers)
                if response.status_code >= 500 and attempt < self._retries:
                    await breaker.record_failure()
                    attempt += 1
                    await asyncio.sleep(0.2 * attempt)
                    continue
                if response.status_code >= 500:
                    await breaker.record_failure()
                else:
                    await breaker.record_success()
                return response
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError) as exc:
                last_error = exc
                await breaker.record_failure()
                attempt += 1
                if attempt > self._retries:
                    break
                await asyncio.sleep(0.2 * attempt)
        assert last_error is not None  # loop only exits after an exception
        raise last_error
