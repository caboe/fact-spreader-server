"""Provider and model rows shared by the bootstrap CLI and the setup wizard.

Provider keys are encrypted here and never returned. The probe is a connectivity and
credential test (the OpenAI-compatible model list), not a capability probe: the fuller
capability matrix arrives in Phase 6.
"""

from __future__ import annotations

from decimal import Decimal

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.core.ids import new_id, utcnow
from app.core.security import SecretBox
from app.db.models import ModelRecord, Provider

PROBE_TIMEOUT_SECONDS = 15.0


def box(settings: Settings) -> SecretBox:
    return SecretBox(settings.secret_material)


async def probe_provider(base_url: str, api_key: str | None) -> list[str]:
    """Return the model ids the provider lists, or raise a client-visible error.

    The key is sent only to the configured provider origin and never logged. A provider
    that does not implement ``GET /models`` cannot pass the setup test: the wizard must
    prove that the stored credentials work before checks are enabled.
    """
    url = f"{base_url.rstrip('/')}/models"
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        async with httpx.AsyncClient(
            timeout=PROBE_TIMEOUT_SECONDS, follow_redirects=False
        ) as client:
            response = await client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        raise AppError(
            422,
            "provider_unreachable",
            f"The provider at {base_url} could not be reached.",
        ) from exc
    if response.status_code == 401 or response.status_code == 403:
        raise AppError(
            422,
            "provider_auth_failed",
            "The provider rejected the API key.",
        )
    if response.status_code >= 400:
        raise AppError(
            422,
            "provider_unreachable",
            f"The provider returned HTTP {response.status_code} for its model list.",
        )
    try:
        payload = response.json()
    except ValueError:
        return []
    entries = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        return []
    return [str(entry["id"]) for entry in entries if isinstance(entry, dict) and entry.get("id")]


async def upsert_provider(
    session: AsyncSession,
    settings: Settings,
    *,
    name: str,
    base_url: str,
    api_key: str | None,
    is_local: bool,
) -> Provider:
    provider = (
        await session.execute(select(Provider).where(Provider.name == name))
    ).scalar_one_or_none()
    encrypted = box(settings).encrypt(api_key) if api_key else None
    if provider is None:
        provider = Provider(
            id=new_id("prv"),
            name=name,
            kind="openai_compatible",
            base_url=base_url.rstrip("/"),
            api_key_enc=encrypted,
            is_local=is_local,
            enabled=True,
            created_at=utcnow(),
        )
        session.add(provider)
        await session.flush()
        return provider
    provider.base_url = base_url.rstrip("/")
    if encrypted is not None:
        provider.api_key_enc = encrypted
    provider.is_local = is_local
    provider.enabled = True
    await session.flush()
    return provider


async def upsert_model(
    session: AsyncSession,
    *,
    provider: Provider,
    alias: str,
    model_name: str,
    capabilities: list[str],
    context_window: int | None,
    embedding_dim: int | None,
    multilingual: bool,
    is_local: bool,
    input_cost: Decimal,
    output_cost: Decimal,
) -> ModelRecord:
    model = (
        await session.execute(select(ModelRecord).where(ModelRecord.gateway_alias == alias))
    ).scalar_one_or_none()
    if model is None:
        model = ModelRecord(
            id=new_id("mdl"),
            provider_id=provider.id,
            gateway_alias=alias,
            model_name=model_name,
            capabilities=capabilities,
            context_window=context_window,
            embedding_dim=embedding_dim,
            multilingual=multilingual,
            is_local=is_local,
            enabled=True,
            input_cost_per_mtok=input_cost,
            output_cost_per_mtok=output_cost,
            created_at=utcnow(),
        )
        session.add(model)
    else:
        model.provider_id = provider.id
        model.model_name = model_name
        model.capabilities = capabilities
        model.context_window = context_window
        model.embedding_dim = embedding_dim
        model.multilingual = multilingual
        model.is_local = is_local
        model.enabled = True
        model.input_cost_per_mtok = input_cost
        model.output_cost_per_mtok = output_cost
    await session.flush()
    return model
