"""First-run setup wizard (IMPLEMENT Phase 5, PROTOCOL §4.5).

The wizard replaces ``make bootstrap`` as the normal path: a fresh volume starts with no
instance and no users, and nothing that costs a model call runs until setup is complete.
Every step is idempotent-safe: a repeated call updates the same rows, never a second admin.

The wizard is reachable without a session only while no admin exists, and even then it
requires the deployment's ``SETUP_TOKEN``. That keeps a publicly reachable fresh instance
from being claimed by the first visitor (DECISIONS D47).
"""

from __future__ import annotations

import hmac
import secrets
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any

import pyotp
from fastapi import Depends
from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.api import ModerationInfo
from app.core.config import Settings
from app.core.errors import AppError
from app.core.ids import new_id, utcnow
from app.core.security import hash_password, validate_password
from app.db.models import (
    AuditLog,
    Instance,
    ModelRecord,
    Provider,
    Setting,
    User,
)
from app.db.session import get_session
from app.llm.aliases import FS_AUDIT, FS_CHAT, FS_EMBEDDING, FS_EXTRACT, FS_MODERATION, FS_VERIFY
from app.llm.client import LLMClient
from app.services.auth import TOTP_ISSUER, new_recovery_codes
from app.services.moderation import ModerationService
from app.services.providers import probe_provider, upsert_model, upsert_provider

STEPS: tuple[str, ...] = ("admin", "totp", "organization", "provider", "models", "moderation")
CHAT_ALIASES = (FS_CHAT, FS_EXTRACT, FS_VERIFY, FS_AUDIT, FS_MODERATION)
SETUP_MODERATION_SAMPLE = "The city council approved the budget on Tuesday."


def _setting_key(name: str) -> str:
    return f"setup.{name}"


async def _read_setting(session: AsyncSession, name: str) -> dict[str, Any] | None:
    row = await session.get(Setting, _setting_key(name))
    return dict(row.value) if row is not None else None


async def _write_setting(
    session: AsyncSession, name: str, value: dict[str, Any], *, now: datetime | None = None
) -> None:
    timestamp = now or utcnow()
    row = await session.get(Setting, _setting_key(name))
    if row is None:
        session.add(Setting(key=_setting_key(name), value=value, updated_at=timestamp))
    else:
        row.value = value
        row.updated_at = timestamp


async def get_instance(session: AsyncSession) -> Instance | None:
    return (await session.execute(select(Instance).limit(1))).scalar_one_or_none()


async def setup_state(session: AsyncSession, settings: Settings) -> dict[str, Any]:
    instance = await get_instance(session)
    admin = await _read_setting(session, "admin")
    totp_confirmed = bool(admin and admin.get("totp_confirmed"))
    organization = await _read_setting(session, "organization")
    provider = await _read_setting(session, "provider")
    models = await _read_setting(session, "models")
    moderation = await _read_setting(session, "moderation")
    complete = bool(instance and instance.setup_complete)
    steps = {
        "admin": admin is not None,
        "totp": totp_confirmed,
        "organization": organization is not None,
        "provider": provider is not None,
        "models": models is not None,
        "moderation": moderation is not None,
    }
    next_step = next((name for name in STEPS if not steps[name]), None)
    return {
        "started": admin is not None,
        "complete": complete,
        "setup_token_required": bool(settings.setup_token.get_secret_value()),
        "steps": steps,
        "next_step": None if complete else next_step,
        "instance": None
        if instance is None
        else {
            "name": instance.name,
            "organization": instance.organization,
            "contact": instance.contact,
        },
    }


def verify_setup_token(settings: Settings, token: str) -> None:
    expected = settings.setup_token.get_secret_value()
    if not expected:
        raise AppError(
            403,
            "setup_token_not_configured",
            "Set SETUP_TOKEN on the deployment before opening the setup wizard.",
        )
    if not hmac.compare_digest(expected, token):
        raise AppError(403, "invalid_setup_token", "The setup token is invalid.")


async def require_setup_open(session: AsyncSession) -> Instance | None:
    instance = await get_instance(session)
    if instance is not None and instance.setup_complete:
        raise AppError(409, "setup_complete", "Setup is already complete.")
    return instance


async def create_admin(
    session: AsyncSession,
    settings: Settings,
    *,
    token: str,
    email: str,
    password: str,
    display_name: str,
) -> tuple[User, str]:
    verify_setup_token(settings, token)
    await require_setup_open(session)
    address = email.casefold().strip()
    if "@" not in address or len(address) < 5:
        raise AppError(422, "invalid_email", "Enter a valid email address.")
    validate_password(password, address)
    if (await session.execute(select(exists().where(User.id.isnot(None))))).scalar_one():
        raise AppError(409, "setup_already_started", "An account already exists.")
    now = utcnow()
    instance = await get_instance(session)
    if instance is None:
        instance = Instance(
            id=new_id("inst"),
            name="Fact Spreader",
            organization=None,
            contact=None,
            setup_complete=False,
            overview_public=False,
            corpus_version="sha256:empty",
            monthly_budget_usd=Decimal(str(settings.monthly_budget_usd)),
            created_at=now,
            updated_at=now,
        )
        session.add(instance)
        await session.flush()
    user = User(
        id=new_id("usr"),
        email=address,
        display_name=display_name,
        password_hash=hash_password(password),
        roles=["admin"],
        permissions=[],
        denied_permissions=[],
        requests_per_day=settings.requests_per_day,
        text_chars=settings.user_text_chars,
        max_file_bytes=settings.user_max_file_bytes,
        max_batch_files=settings.user_max_batch_files,
        is_active=True,
        totp_secret_enc=None,
        totp_enabled=False,
        totp_recovery_codes=[],
        llm_budget_usd=Decimal(str(settings.user_budget_usd)),
        created_at=now,
        updated_at=now,
    )
    secret = pyotp.random_base32()
    from app.services.auth import encrypt_totp_secret

    user.totp_secret_enc = encrypt_totp_secret(settings, secret)
    session.add(user)
    await session.flush()
    await _write_setting(
        session,
        "admin",
        {
            "user_id": user.id,
            "email": user.email,
            "created_at": now.isoformat(),
            "totp_confirmed": False,
        },
        now=now,
    )
    session.add(
        AuditLog(
            id=new_id("aud"),
            actor_id=None,
            actor_type="system",
            action="setup_admin_created",
            object_type="user",
            object_id=user.id,
            detail={"email": user.email},
            created_at=now,
        )
    )
    await session.commit()
    return user, secret


def provisioning_uri(secret: str, email: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=TOTP_ISSUER)


async def confirm_admin_totp(
    session: AsyncSession, settings: Settings, *, token: str, code: str
) -> list[str]:
    verify_setup_token(settings, token)
    admin = await _read_setting(session, "admin")
    if admin is None:
        raise AppError(409, "setup_step_missing", "Create the administrator account first.")
    user = await session.get(User, str(admin["user_id"]))
    if user is None or user.totp_secret_enc is None:
        raise AppError(409, "setup_step_missing", "Create the administrator account first.")
    from app.services.auth import decrypt_totp_secret

    secret = decrypt_totp_secret(settings, user.totp_secret_enc)
    if not pyotp.TOTP(secret).verify(code.strip(), valid_window=1):
        raise AppError(401, "invalid_totp", "The TOTP code is invalid.")
    plain, hashed = new_recovery_codes()
    user.totp_enabled = True
    user.totp_recovery_codes = hashed
    user.updated_at = utcnow()
    admin["totp_confirmed"] = True
    await _write_setting(session, "admin", admin)
    session.add(
        AuditLog(
            id=new_id("aud"),
            actor_id=user.id,
            actor_type="user",
            action="setup_totp_confirmed",
            object_type="user",
            object_id=user.id,
            detail={},
            created_at=utcnow(),
        )
    )
    await session.commit()
    return plain


async def set_organization(
    session: AsyncSession,
    *,
    name: str,
    organization: str | None,
    contact: str | None,
    overview_public: bool,
    monthly_budget_usd: float | None,
) -> None:
    await require_setup_open(session)
    admin = await _read_setting(session, "admin")
    if admin is None:
        raise AppError(409, "setup_step_missing", "Create the administrator account first.")
    if monthly_budget_usd is not None and monthly_budget_usd <= 0:
        raise AppError(422, "invalid_budget", "The monthly budget must be positive.")
    instance = await get_instance(session)
    assert instance is not None  # the admin step creates it
    instance.name = name
    instance.organization = organization
    instance.contact = contact
    instance.overview_public = overview_public
    if monthly_budget_usd is not None:
        instance.monthly_budget_usd = Decimal(str(monthly_budget_usd))
    instance.updated_at = utcnow()
    await _write_setting(
        session,
        "organization",
        {"name": name, "organization": organization, "contact": contact},
    )
    await session.commit()


async def configure_provider(
    session: AsyncSession,
    settings: Settings,
    *,
    name: str,
    base_url: str,
    api_key: str | None,
    is_local: bool,
    use: str = "chat",
) -> tuple[Provider, list[str]]:
    await require_setup_open(session)
    if not base_url.startswith(("http://", "https://")):
        raise AppError(422, "invalid_provider_url", "The provider URL must be HTTP(S).")
    if not is_local and not api_key:
        raise AppError(422, "provider_key_required", "An external provider needs an API key.")
    models = await probe_provider(base_url, api_key)
    provider = await upsert_provider(
        session,
        settings,
        name=name,
        base_url=base_url,
        api_key=api_key,
        is_local=is_local,
    )
    key = "provider" if use == "chat" else "provider_embedding"
    await _write_setting(
        session,
        key,
        {
            "provider_id": provider.id,
            "name": name,
            "base_url": provider.base_url,
            "is_local": is_local,
            "model_count": len(models),
            "tested_at": utcnow().isoformat(),
        },
    )
    session.add(
        AuditLog(
            id=new_id("aud"),
            actor_id=None,
            actor_type="system",
            action="setup_provider_tested",
            object_type="provider",
            object_id=provider.id,
            detail={"name": name, "base_url": provider.base_url, "models": len(models)},
            created_at=utcnow(),
        )
    )
    await session.commit()
    return provider, models


async def assign_models(
    session: AsyncSession,
    settings: Settings,
    *,
    chat_model: str,
    embedding_model: str,
    embedding_dim: int | None,
    multilingual: bool,
) -> list[ModelRecord]:
    await require_setup_open(session)
    provider_state = await _read_setting(session, "provider")
    if provider_state is None:
        raise AppError(409, "setup_step_missing", "Test a provider before assigning models.")
    provider = await session.get(Provider, str(provider_state["provider_id"]))
    if provider is None:
        raise AppError(409, "setup_step_missing", "Test a provider before assigning models.")
    embedding_state = await _read_setting(session, "provider_embedding") or provider_state
    embedding_provider = await session.get(Provider, str(embedding_state["provider_id"]))
    if embedding_provider is None:
        raise AppError(409, "setup_step_missing", "Test a provider before assigning models.")
    if embedding_dim is not None and embedding_dim != settings.embedding_dim:
        raise AppError(
            422,
            "embedding_dim_mismatch",
            f"The corpus embedding dimension is {settings.embedding_dim}.",
        )
    models: list[ModelRecord] = []
    for alias in CHAT_ALIASES:
        models.append(
            await upsert_model(
                session,
                provider=provider,
                alias=alias,
                model_name=chat_model,
                capabilities=["chat", "structured_output"],
                context_window=128_000,
                embedding_dim=None,
                multilingual=multilingual,
                is_local=provider.is_local,
                input_cost=Decimal(str(settings.llm_input_cost_per_mtok)),
                output_cost=Decimal(str(settings.llm_output_cost_per_mtok)),
            )
        )
    models.append(
        await upsert_model(
            session,
            provider=embedding_provider,
            alias=FS_EMBEDDING,
            model_name=embedding_model,
            capabilities=["embedding"],
            context_window=8192,
            embedding_dim=settings.embedding_dim,
            multilingual=True,
            is_local=embedding_provider.is_local,
            input_cost=Decimal("0"),
            output_cost=Decimal("0"),
        )
    )
    await _write_setting(
        session,
        "models",
        {
            "provider_id": provider.id,
            "chat_model": chat_model,
            "embedding_model": embedding_model,
            "aliases": [*CHAT_ALIASES, FS_EMBEDDING],
            "assigned_at": utcnow().isoformat(),
        },
    )
    allow_external = not provider.is_local or not embedding_provider.is_local
    for name, value in (
        ("data_flow.allow_external", {"allow": allow_external}),
        ("moderation.backend", {"alias": FS_MODERATION}),
    ):
        row = await session.get(Setting, name)
        if row is None:
            session.add(Setting(key=name, value=value, updated_at=utcnow()))
        else:
            row.value = value
            row.updated_at = utcnow()
    await session.commit()
    return models


async def _moderation_result(settings: Settings) -> ModerationInfo:
    service = ModerationService(LLMClient(settings, consumer="setup"))
    return await service.classify_check(SETUP_MODERATION_SAMPLE, user_id=None)


async def run_moderation_test(session: AsyncSession, settings: Settings) -> ModerationInfo:
    await require_setup_open(session)
    models_state = await _read_setting(session, "models")
    if models_state is None:
        raise AppError(409, "setup_step_missing", "Assign models before testing moderation.")
    result = await _moderation_result(settings)
    if result.flagged:
        raise AppError(
            422,
            "moderation_test_failed",
            "The classifier flagged the benign sample; its configuration is not usable.",
        )
    await _write_setting(
        session,
        "moderation",
        {
            "backend": result.backend,
            "flagged": False,
            "tested_at": utcnow().isoformat(),
        },
    )
    await session.commit()
    return result


def _missing_steps(state: dict[str, Any]) -> list[str]:
    steps = state["steps"]
    return [name for name in STEPS if not steps[name]]


async def complete_setup(session: AsyncSession, settings: Settings) -> Instance:
    instance = await require_setup_open(session)
    state = await setup_state(session, settings)
    missing = _missing_steps(state)
    if missing:
        raise AppError(
            409,
            "setup_step_missing",
            "Finish these setup steps first: " + ", ".join(missing),
        )
    assert instance is not None
    now = utcnow()
    instance.setup_complete = True
    instance.updated_at = now
    await _write_setting(session, "completed", {"completed_at": now.isoformat()}, now=now)
    session.add(
        AuditLog(
            id=new_id("aud"),
            actor_id=None,
            actor_type="system",
            action="setup_completed",
            object_type="instance",
            object_id=instance.id,
            detail={"steps": list(STEPS)},
            created_at=now,
        )
    )
    await session.commit()
    return instance


async def setup_gate(session: AsyncSession) -> None:
    """Refuse until setup is complete (IMPLEMENT Phase 5)."""
    instance = await get_instance(session)
    if instance is None or not instance.setup_complete:
        raise AppError(
            503,
            "setup_required",
            "The instance is not set up yet; complete the setup wizard first.",
        )


async def setup_gate_dependency(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    await setup_gate(session)


def new_setup_token() -> str:
    """A token for .env.example and tests; never stored in the database."""
    return secrets.token_urlsafe(24)
