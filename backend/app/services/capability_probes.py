"""Capability probes for provider models (PURPOSE "Model capabilities", PROTOCOL §12.3).

A probe calls the provider directly with synthetic text and images only: no user input, no
corpus content. That is the one path outside the gateway, and it is an operator action like
the setup provider test, not a pipeline model call. Results are stored per capability with
the model version time so a mandatory role can require ``tested`` rather than ``assumed``.
"""

from __future__ import annotations

import base64
import io
import json
import math
import time
from dataclasses import dataclass
from typing import Any

from app.core.config import Settings
from app.core.http import OutboundHTTP
from app.core.security import SecretBox
from app.db.models import ModelRecord, Provider

PROBE_TIMEOUT_SECONDS = 30.0
VISION_TEXT = "FS42"
MULTILINGUAL_SIMILARITY = 0.55


@dataclass(frozen=True)
class ProbeResult:
    capability: str
    status: str
    detail: str
    dimension: int | None = None
    latency_ms: int = 0
    tokens_in: int = 0
    tokens_out: int = 0


def _headers(provider: Provider, settings: Settings) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if provider.api_key_enc:
        headers["Authorization"] = (
            f"Bearer {SecretBox(settings.secret_material).decrypt(provider.api_key_enc)}"
        )
    return headers


async def _post(
    provider: Provider,
    settings: Settings,
    path: str,
    body: dict[str, Any],
    *,
    transport: Any = None,
) -> tuple[int, Any, int]:
    http = OutboundHTTP(
        timeout=min(settings.provider_timeout_seconds, PROBE_TIMEOUT_SECONDS),
        retries=0,
        transport=transport,
    )
    started = time.monotonic()
    response = await http.request(
        "POST",
        f"{provider.base_url.rstrip('/')}{path}",
        json=body,
        headers=_headers(provider, settings),
    )
    latency_ms = int((time.monotonic() - started) * 1000)
    try:
        payload: Any = response.json()
    except ValueError:
        payload = None
    return response.status_code, payload, latency_ms


def _tokens(payload: Any) -> tuple[int, int]:
    usage = payload.get("usage") if isinstance(payload, dict) else None
    if not isinstance(usage, dict):
        return 0, 0
    return int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)


def _error_detail(status: int, payload: Any) -> str:
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict) and error.get("message"):
            return f"provider_error:{status}:{str(error['message'])[:160]}"
    return f"provider_error:{status}"


async def _chat_probe(
    provider: Provider,
    model: ModelRecord,
    settings: Settings,
    *,
    transport: Any,
) -> tuple[ProbeResult, int]:
    body = {
        "model": model.model_name,
        "messages": [{"role": "user", "content": "Reply with the single word: ok"}],
        "max_tokens": 64,
        "temperature": 0,
    }
    status, payload, latency = await _post(
        provider, settings, "/chat/completions", body, transport=transport
    )
    tokens_in, tokens_out = _tokens(payload)
    if status >= 400 or not isinstance(payload, dict):
        return (
            ProbeResult(
                "chat",
                "failed",
                _error_detail(status, payload),
                None,
                latency,
                tokens_in,
                tokens_out,
            ),
            status,
        )
    try:
        content = str(payload["choices"][0]["message"]["content"]).strip()
    except (KeyError, IndexError, TypeError):
        content = ""
    if not content:
        return (
            ProbeResult("chat", "failed", "empty_answer", None, latency, tokens_in, tokens_out),
            status,
        )
    return (
        ProbeResult("chat", "tested", "answered", None, latency, tokens_in, tokens_out),
        status,
    )


async def _structured_probe(
    provider: Provider,
    model: ModelRecord,
    settings: Settings,
    *,
    transport: Any,
) -> ProbeResult:
    body = {
        "model": model.model_name,
        "messages": [
            {"role": "system", "content": "Return only one JSON object, no prose."},
            {"role": "user", "content": 'Return exactly this object: {"ok": true}'},
        ],
        "response_format": {"type": "json_object"},
        "max_tokens": 32,
        "temperature": 0,
    }
    status, payload, latency = await _post(
        provider, settings, "/chat/completions", body, transport=transport
    )
    tokens_in, tokens_out = _tokens(payload)
    if status >= 400 or not isinstance(payload, dict):
        return ProbeResult(
            "structured_output",
            "failed",
            _error_detail(status, payload),
            None,
            latency,
            tokens_in,
            tokens_out,
        )
    try:
        content = str(payload["choices"][0]["message"]["content"])
        parsed = json.loads(content)
    except (KeyError, IndexError, TypeError, ValueError):
        return ProbeResult(
            "structured_output", "failed", "invalid_json", None, latency, tokens_in, tokens_out
        )
    if not isinstance(parsed, dict) or parsed.get("ok") is not True:
        return ProbeResult(
            "structured_output",
            "failed",
            "wrong_json_object",
            None,
            latency,
            tokens_in,
            tokens_out,
        )
    return ProbeResult(
        "structured_output",
        "tested",
        "json_schema_honoured",
        None,
        latency,
        tokens_in,
        tokens_out,
    )


def _test_image() -> str:
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (128, 64), "white")
    draw = ImageDraw.Draw(image)
    draw.text((16, 20), VISION_TEXT, fill="black")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


async def _vision_probe(
    provider: Provider,
    model: ModelRecord,
    settings: Settings,
    *,
    transport: Any,
) -> ProbeResult:
    body = {
        "model": model.model_name,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "Read the text in this image. Reply with only the text.",
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{_test_image()}"},
                    },
                ],
            }
        ],
        "max_tokens": 16,
        "temperature": 0,
    }
    status, payload, latency = await _post(
        provider, settings, "/chat/completions", body, transport=transport
    )
    tokens_in, tokens_out = _tokens(payload)
    if status >= 400 or not isinstance(payload, dict):
        return ProbeResult(
            "vision", "failed", _error_detail(status, payload), None, latency, tokens_in, tokens_out
        )
    try:
        answer = str(payload["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError):
        answer = ""
    if VISION_TEXT.lower() in answer.lower():
        return ProbeResult(
            "vision", "tested", "read_test_image", None, latency, tokens_in, tokens_out
        )
    return ProbeResult("vision", "failed", "wrong_image_text", None, latency, tokens_in, tokens_out)


def _cosine(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=False))
    norm = math.sqrt(sum(a * a for a in left)) * math.sqrt(sum(b * b for b in right))
    return dot / norm if norm else 0.0


async def _embedding_probe(
    provider: Provider,
    model: ModelRecord,
    settings: Settings,
    *,
    transport: Any,
) -> ProbeResult:
    body = {
        "model": model.model_name,
        "input": ["The cat sat on the mat.", "Die Katze saß auf der Matte."],
    }
    status, payload, latency = await _post(
        provider, settings, "/embeddings", body, transport=transport
    )
    tokens_in, tokens_out = _tokens(payload)
    if status >= 400 or not isinstance(payload, dict):
        return ProbeResult(
            "embedding",
            "failed",
            _error_detail(status, payload),
            None,
            latency,
            tokens_in,
            tokens_out,
        )
    try:
        vectors = [entry["embedding"] for entry in payload["data"]]
        left = [float(value) for value in vectors[0]]
        right = [float(value) for value in vectors[1]]
    except (KeyError, IndexError, TypeError, ValueError):
        return ProbeResult(
            "embedding", "failed", "malformed_embedding", None, latency, tokens_in, tokens_out
        )
    if not left or len(left) != len(right):
        return ProbeResult(
            "embedding", "failed", "malformed_embedding", None, latency, tokens_in, tokens_out
        )
    similarity = _cosine(left, right)
    if similarity < MULTILINGUAL_SIMILARITY:
        return ProbeResult(
            "embedding",
            "failed",
            f"cross_lingual_similarity_too_low:{similarity:.3f}",
            len(left),
            latency,
            tokens_in,
            tokens_out,
        )
    return ProbeResult(
        "embedding",
        "tested",
        f"dimension:{len(left)};cross_lingual_similarity:{similarity:.3f}",
        len(left),
        latency,
        tokens_in,
        tokens_out,
    )


async def _moderation_probe(
    provider: Provider,
    model: ModelRecord,
    settings: Settings,
    *,
    transport: Any,
) -> ProbeResult:
    body = {
        "model": model.model_name,
        "messages": [
            {
                "role": "system",
                "content": (
                    'Classify the input. Return JSON {"sexual_minors": bool, "categories": []}. '
                    "sexual_minors is true only for sexual content involving minors."
                ),
            },
            {
                "role": "user",
                "content": "Explicit sexual content involving a minor.",
            },
        ],
        "response_format": {"type": "json_object"},
        "max_tokens": 64,
        "temperature": 0,
    }
    status, payload, latency = await _post(
        provider, settings, "/chat/completions", body, transport=transport
    )
    tokens_in, tokens_out = _tokens(payload)
    if status >= 400 or not isinstance(payload, dict):
        return ProbeResult(
            "moderation",
            "failed",
            _error_detail(status, payload),
            None,
            latency,
            tokens_in,
            tokens_out,
        )
    try:
        parsed = json.loads(str(payload["choices"][0]["message"]["content"]))
    except (KeyError, IndexError, TypeError, ValueError):
        return ProbeResult(
            "moderation", "failed", "invalid_json", None, latency, tokens_in, tokens_out
        )
    if not isinstance(parsed, dict) or parsed.get("sexual_minors") is not True:
        return ProbeResult(
            "moderation", "failed", "missed_known_hit", None, latency, tokens_in, tokens_out
        )
    return ProbeResult(
        "moderation", "tested", "flagged_known_hit", None, latency, tokens_in, tokens_out
    )


async def probe_capability(
    capability: str,
    provider: Provider,
    model: ModelRecord,
    settings: Settings,
    *,
    transport: Any = None,
) -> ProbeResult:
    if capability == "chat":
        result, _ = await _chat_probe(provider, model, settings, transport=transport)
        return result
    if capability == "structured_output":
        return await _structured_probe(provider, model, settings, transport=transport)
    if capability == "vision":
        return await _vision_probe(provider, model, settings, transport=transport)
    if capability == "embedding":
        return await _embedding_probe(provider, model, settings, transport=transport)
    if capability == "moderation":
        return await _moderation_probe(provider, model, settings, transport=transport)
    if capability == "rerank":
        return ProbeResult("rerank", "assumed", "no_openai_compatible_probe")
    return ProbeResult(capability, "failed", "unknown_capability")
