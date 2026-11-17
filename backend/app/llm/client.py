"""Client for the internal LLM gateway, with schema validation and one repair attempt.

The pipeline never talks to a provider directly (hard invariant 8). This client only knows
the internal OpenAI-compatible endpoint; provider routing, data-flow policy, budgets and
usage accounting live behind it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from app.core.config import Settings
from app.core.http import OutboundHTTP

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    def __init__(self, status: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.code = code
        self.detail = detail


class LLMOutputError(LLMError):
    def __init__(self, detail: str) -> None:
        super().__init__(502, "invalid_model_output", detail)


@dataclass(frozen=True)
class LLMUsage:
    tokens_in: int = 0
    tokens_out: int = 0


class TextLLM(Protocol):
    async def chat_text(
        self,
        *,
        alias: str,
        messages: list[dict[str, str]],
        data_classes: list[str],
        purpose: str,
        user_id: str | None = None,
        max_tokens: int = 1200,
        temperature: float = 0.4,
    ) -> tuple[str, LLMUsage]: ...


class StructuredLLM(Protocol):
    async def chat_structured(
        self,
        *,
        alias: str,
        messages: list[dict[str, str]],
        output_model: type[T],
        data_classes: list[str],
        purpose: str,
        user_id: str | None = None,
        max_tokens: int = 2048,
    ) -> tuple[T, LLMUsage]: ...


class RenderLLM(StructuredLLM, TextLLM, Protocol):
    pass


class LLMClient:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: Any = None,
        consumer: str = "pipeline",
        request_id: str | None = None,
    ) -> None:
        self._settings = settings
        self._http = OutboundHTTP(
            timeout=settings.provider_timeout_seconds,
            retries=1,
            transport=transport,
        )
        self._consumer = consumer
        self._request_id = request_id
        self._base = settings.internal_gateway_url.rstrip("/")
        self._key = settings.internal_llm_key.get_secret_value()

    async def chat_structured(
        self,
        *,
        alias: str,
        messages: list[dict[str, str]],
        output_model: type[T],
        data_classes: list[str],
        purpose: str,
        user_id: str | None = None,
        max_tokens: int = 2048,
    ) -> tuple[T, LLMUsage]:
        schema = json.dumps(output_model.model_json_schema(), ensure_ascii=False)
        full_messages = [
            *messages,
            {
                "role": "system",
                "content": (
                    "Return only one JSON object matching this JSON Schema. Do not add prose, "
                    "markdown fences or fields that are not in the schema.\n" + schema
                ),
            },
        ]
        raw, usage = await self._call(
            alias=alias,
            messages=full_messages,
            data_classes=data_classes,
            purpose=purpose,
            user_id=user_id,
            max_tokens=max_tokens,
        )
        try:
            return self._validate(raw, output_model), usage
        except (json.JSONDecodeError, ValidationError) as first_error:
            repair_messages = [
                *full_messages,
                {"role": "assistant", "content": raw},
                {
                    "role": "user",
                    "content": (
                        "That output did not validate. Fix it and return only valid JSON. "
                        f"Validation error: {first_error}"
                    ),
                },
            ]
            repaired, repaired_usage = await self._call(
                alias=alias,
                messages=repair_messages,
                data_classes=data_classes,
                purpose=purpose,
                user_id=user_id,
                max_tokens=max_tokens,
            )
            try:
                return self._validate(repaired, output_model), LLMUsage(
                    tokens_in=usage.tokens_in + repaired_usage.tokens_in,
                    tokens_out=usage.tokens_out + repaired_usage.tokens_out,
                )
            except (json.JSONDecodeError, ValidationError) as second_error:
                raise LLMOutputError(
                    f"model output failed validation twice: {second_error}"
                ) from second_error

    @staticmethod
    def _validate(raw: str, output_model: type[T]) -> T:
        text = raw.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        # Some providers prepend a sentence despite JSON mode. Take the outermost object.
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]
        return output_model.model_validate_json(text)

    async def chat_text(
        self,
        *,
        alias: str,
        messages: list[dict[str, str]],
        data_classes: list[str],
        purpose: str,
        user_id: str | None = None,
        max_tokens: int = 1200,
        temperature: float = 0.4,
    ) -> tuple[str, LLMUsage]:
        headers = {
            "Authorization": f"Bearer {self._key}",
            "X-FS-Consumer": self._consumer,
            "X-FS-Data-Classes": ",".join(data_classes),
            "X-FS-Purpose": purpose,
            "Content-Type": "application/json",
        }
        if user_id:
            headers["X-FS-User-Id"] = user_id
        if self._request_id:
            headers["X-Request-Id"] = self._request_id
        body = {
            "model": alias,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        response = await self._http.request(
            "POST",
            f"{self._base}/chat/completions",
            json=body,
            headers=headers,
        )
        if response.status_code >= 400:
            raise _gateway_error(response)
        try:
            payload = response.json()
            content = payload["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMOutputError("gateway returned a malformed chat completion") from exc
        if not isinstance(content, str) or not content.strip():
            raise LLMOutputError("the model returned an empty narrative")
        usage = payload.get("usage") or {}
        return content.strip(), LLMUsage(
            tokens_in=int(usage.get("prompt_tokens") or 0),
            tokens_out=int(usage.get("completion_tokens") or 0),
        )

    async def _call(
        self,
        *,
        alias: str,
        messages: list[dict[str, str]],
        data_classes: list[str],
        purpose: str,
        user_id: str | None,
        max_tokens: int,
    ) -> tuple[str, LLMUsage]:
        headers = {
            "Authorization": f"Bearer {self._key}",
            "X-FS-Consumer": self._consumer,
            "X-FS-Data-Classes": ",".join(data_classes),
            "X-FS-Purpose": purpose,
            "Content-Type": "application/json",
        }
        if user_id:
            headers["X-FS-User-Id"] = user_id
        if self._request_id:
            headers["X-Request-Id"] = self._request_id
        body = {
            "model": alias,
            "messages": messages,
            "temperature": 0,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }
        response = await self._http.request(
            "POST",
            f"{self._base}/chat/completions",
            json=body,
            headers=headers,
        )
        if response.status_code >= 400:
            raise _gateway_error(response)
        try:
            payload = response.json()
            content = payload["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMOutputError("gateway returned a malformed chat completion") from exc
        usage = payload.get("usage") or {}
        return str(content), LLMUsage(
            tokens_in=int(usage.get("prompt_tokens") or 0),
            tokens_out=int(usage.get("completion_tokens") or 0),
        )


def _gateway_error(response: Any) -> LLMError:
    try:
        payload = response.json()
        error = payload.get("error") or {}
        code = str(error.get("code") or "provider_error")
        detail = str(error.get("message") or "LLM gateway request failed")
    except ValueError:
        code = "provider_error"
        detail = f"LLM gateway returned HTTP {response.status_code}"
    if response.status_code == 429 and code == "budget_exceeded":
        return LLMError(429, "budget_exceeded", detail)
    if response.status_code == 403 and code == "data_flow_blocked":
        return LLMError(403, "data_flow_blocked", detail)
    if code == "circuit_open":
        return LLMError(503, "circuit_open", detail)
    return LLMError(response.status_code if response.status_code >= 500 else 502, code, detail)
