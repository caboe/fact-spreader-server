"""Phase 1 operator CLI: bootstrap, explicit fixture approval/index, API keys, spend.

The setup wizard and editorial UI replace the bootstrap and fixture paths in Phases 4-5.
Until then, the CLI is the only way to create an admin and to approve the synthetic
fixtures. It is deliberately explicit: ``seed-fixtures`` refuses to run without
``--approve`` and records the admin as the approver.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.ids import new_id, sha256_text, utcnow
from app.core.security import hash_password
from app.db.models import (
    ApiKey,
    Document,
    DocumentVersion,
    Instance,
    Result,
    Setting,
    UsageEvent,
    User,
)
from app.db.models import (
    Job as JobRow,
)
from app.db.session import Database
from app.llm.aliases import (
    FS_AUDIT,
    FS_CHAT,
    FS_EMBEDDING,
    FS_EXTRACT,
    FS_MODERATION,
    FS_VERIFY,
    FS_VISION,
)
from app.retrieval.lightrag import LightRAGClient
from app.services.auth import all_permissions, create_api_key
from app.services.providers import upsert_model, upsert_provider
from app.services.publishers import PublisherMatch, PublisherRegistry
from app.services.retention import run_retention

DEFAULT_FIXTURES = (
    "crime-raw-suspect-rates",
    "crime-adjusted-study",
    "crime-age-curve",
    "crime-convictions-international",
    "crime-pks-methodology-de",
    "crime-adjusted-study-shared-dataset",
    "crime-contradiction-a",
    "crime-contradiction-b",
    "crime-stale-figure",
    "crime-german-only",
)


async def bootstrap(settings: Settings, *, print_api_key: bool) -> int:
    database = Database(settings)
    try:
        async with database.session_factory() as session:
            instance = (await session.execute(select(Instance).limit(1))).scalar_one_or_none()
            now = utcnow()
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
            admin = (
                await session.execute(
                    select(User).where(User.email == settings.bootstrap_admin_email.casefold())
                )
            ).scalar_one_or_none()
            if admin is None:
                admin = User(
                    id=new_id("usr"),
                    email=settings.bootstrap_admin_email.casefold(),
                    display_name="Administrator",
                    password_hash=hash_password(
                        settings.bootstrap_admin_password.get_secret_value()
                    ),
                    permissions=all_permissions(),
                    roles=["admin"],
                    requests_per_day=settings.requests_per_day,
                    text_chars=settings.user_text_chars,
                    max_file_bytes=settings.user_max_file_bytes,
                    max_batch_files=settings.user_max_batch_files,
                    is_active=True,
                    llm_budget_usd=Decimal(str(settings.user_budget_usd)),
                    created_at=now,
                    updated_at=now,
                )
                session.add(admin)
                await session.flush()
            else:
                admin.permissions = all_permissions()
                admin.roles = ["admin"]
                admin.requests_per_day = settings.requests_per_day
                admin.text_chars = settings.user_text_chars
                admin.max_file_bytes = settings.user_max_file_bytes
                admin.max_batch_files = settings.user_max_batch_files
                admin.is_active = True
                admin.llm_budget_usd = Decimal(str(settings.user_budget_usd))
            if not settings.deepseek_api_key.get_secret_value():
                print("DEEPSEEK_API_KEY is required for the Phase 1 bootstrap.", file=sys.stderr)
                return 2
            chat_provider = await upsert_provider(
                session,
                settings,
                name="deepseek",
                base_url=settings.provider_chat_base_url,
                api_key=settings.deepseek_api_key.get_secret_value(),
                is_local=False,
            )
            embedding_provider = await upsert_provider(
                session,
                settings,
                name="ollama-local",
                base_url=settings.provider_embedding_base_url,
                api_key=None,
                is_local=True,
            )
            for alias in (FS_CHAT, FS_EXTRACT, FS_VERIFY, FS_AUDIT, FS_MODERATION):
                await upsert_model(
                    session,
                    provider=chat_provider,
                    alias=alias,
                    model_name=settings.provider_chat_model,
                    capabilities=["chat", "structured_output"],
                    context_window=128_000,
                    embedding_dim=None,
                    multilingual=False,
                    is_local=False,
                    input_cost=Decimal(str(settings.llm_input_cost_per_mtok)),
                    output_cost=Decimal(str(settings.llm_output_cost_per_mtok)),
                )
            await upsert_model(
                session,
                provider=embedding_provider,
                alias=FS_EMBEDDING,
                model_name=settings.provider_embedding_model,
                capabilities=["embedding"],
                context_window=8192,
                embedding_dim=settings.embedding_dim,
                multilingual=True,
                is_local=True,
                input_cost=Decimal("0"),
                output_cost=Decimal("0"),
            )
            if settings.vision_enabled and settings.openrouter_api_key.get_secret_value():
                vision_provider = await upsert_provider(
                    session,
                    settings,
                    name="openrouter",
                    base_url=settings.provider_vision_base_url,
                    api_key=settings.openrouter_api_key.get_secret_value(),
                    is_local=False,
                )
                await upsert_model(
                    session,
                    provider=vision_provider,
                    alias=FS_VISION,
                    model_name=settings.provider_vision_model or "google/gemini-2.5-flash",
                    capabilities=["chat", "vision", "structured_output"],
                    context_window=128_000,
                    embedding_dim=None,
                    multilingual=True,
                    is_local=False,
                    input_cost=Decimal("0.30"),
                    output_cost=Decimal("2.50"),
                )
            setting_updates: dict[str, dict[str, Any]] = {
                "data_flow.allow_external": {"allow": True},
                "moderation.backend": {"alias": FS_MODERATION},
                "setup.bootstrap": {"completed_at": now.isoformat()},
            }
            for setting_key, setting_value in setting_updates.items():
                setting_row = await session.get(Setting, setting_key)
                if setting_row is None:
                    session.add(Setting(key=setting_key, value=setting_value, updated_at=now))
                else:
                    setting_row.value = setting_value
                    setting_row.updated_at = now
            instance.setup_complete = True
            instance.updated_at = now
            await session.flush()
            api_key: str | None = None
            if print_api_key:
                existing_keys = (
                    await session.execute(
                        select(ApiKey).where(ApiKey.user_id == admin.id, ApiKey.name == "smoke")
                    )
                ).scalars()
                for existing_key in existing_keys:
                    existing_key.revoked_at = now
                _key_row, api_key = await create_api_key(
                    session, user=admin, name="smoke", permissions=all_permissions()
                )
            await session.commit()
    finally:
        await database.dispose()
    if print_api_key and api_key:
        print(api_key)
    else:
        print("Bootstrap complete. Admin:", settings.bootstrap_admin_email, file=sys.stderr)
    return 0


def _parse_markdown(path: Path) -> tuple[dict[str, Any], str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError(f"{path.name} has no front matter")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise ValueError(f"{path.name} has an unterminated front matter")
    meta = yaml.safe_load(text[4:end]) or {}
    body = text[end + 5 :].lstrip("\n")
    return meta, body


def _date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


async def seed_fixtures(settings: Settings, *, approve: bool) -> int:
    if not approve:
        print("seed-fixtures requires --approve (there is no automatic approval).", file=sys.stderr)
        return 2
    database = Database(settings)
    lightrag = LightRAGClient(settings)
    exit_code = 0
    try:
        if not await lightrag.health():
            print("LightRAG is not reachable; start the stack first.", file=sys.stderr)
            return 2
        async with database.session_factory() as session:
            instance = (await session.execute(select(Instance).limit(1))).scalar_one_or_none()
            admin = (
                await session.execute(
                    select(User).where(User.email == settings.bootstrap_admin_email.casefold())
                )
            ).scalar_one_or_none()
            if instance is None or admin is None:
                print("Run the bootstrap command first.", file=sys.stderr)
                return 2
            publishers = PublisherRegistry.from_path(settings.publisher_list_path)
            corpus_dir = Path(settings.fixture_corpus_dir)
            inserted: list[tuple[Document, str]] = []
            for key in DEFAULT_FIXTURES:
                path = corpus_dir / f"{key}.md"
                if not path.exists():
                    print(f"missing fixture {path}", file=sys.stderr)
                    exit_code = 1
                    continue
                meta, body = _parse_markdown(path)
                content_hash = sha256_text(body)
                publisher = str(meta.get("publisher") or "Unknown")
                url = meta.get("url")
                doi = meta.get("doi")
                quality = publishers.resolve(publisher=publisher, url=url, doi=doi)
                if quality.grade == "D" and publisher.startswith("Example "):
                    # The synthetic corpus deliberately uses names that are not real
                    # publishers. Its documents are approved by this explicit CLI and get
                    # a document-level override for the evaluation, never a shipped-list
                    # entry. This is fixture data, not a claim about a real institution.
                    from app.contracts.api import SourceQualityBasis

                    quality = PublisherMatch(
                        grade="A",
                        basis=SourceQualityBasis(
                            source="document_override",
                            list_version=publishers.version,
                            entry="fixture-corpus",
                        ),
                    )
                existing = (
                    await session.execute(
                        select(Document).where(
                            Document.content_hash == content_hash, Document.deleted.is_(False)
                        )
                    )
                ).scalar_one_or_none()
                if existing is not None and existing.state == "indexed":
                    existing.source_quality = quality.grade
                    existing.source_quality_basis = quality.basis.model_dump(mode="json")
                    existing.updated_at = utcnow()
                    await session.commit()
                    print(f"skip indexed {key} (grade refreshed)", file=sys.stderr)
                    continue
                document_id = existing.id if existing is not None else new_id("doc")
                now = utcnow()
                if existing is None:
                    document = Document(
                        id=document_id,
                        title=str(meta.get("title") or key),
                        publisher=publisher,
                        authors=list(meta.get("authors") or []),
                        publication_date=_date(meta.get("publication_date")),
                        url=url,
                        doi=doi,
                        dataset_id=meta.get("dataset_id"),
                        source_quality=quality.grade,
                        source_quality_basis=quality.basis.model_dump(mode="json"),
                        domain_tags=list(meta.get("domain_tags") or []),
                        language=str(meta.get("language") or "en"),
                        license=meta.get("license"),
                        redistribution=str(meta.get("redistribution") or "metadata_only"),
                        origin_instance_id=instance.id,
                        origin_document_id=document_id,
                        content_hash=content_hash,
                        state="approved",
                        version=1,
                        submitted_by=admin.id,
                        approved_by=admin.id,
                        approved_at=now,
                        deleted=False,
                        created_at=now,
                        updated_at=now,
                    )
                    session.add(document)
                else:
                    document = existing
                    document.state = "approved"
                    document.source_quality = quality.grade
                    document.source_quality_basis = quality.basis.model_dump(mode="json")
                    document.updated_at = now
                version = (
                    await session.execute(
                        select(DocumentVersion).where(
                            DocumentVersion.document_id == document.id,
                            DocumentVersion.version == document.version,
                        )
                    )
                ).scalar_one_or_none()
                if version is None:
                    version = DocumentVersion(
                        id=new_id("ver"),
                        document_id=document.id,
                        version=document.version,
                        content_hash=content_hash,
                        content_md=body,
                        size_bytes=len(body.encode("utf-8")),
                        created_at=now,
                    )
                    session.add(version)
                await session.flush()
                file_source = f"{document.id}@v{document.version}"
                await lightrag.insert_text(
                    content=body, file_source=file_source, title=document.title
                )
                document.state = "indexing"
                document.updated_at = utcnow()
                inserted.append((document, file_source))
                await session.commit()
                print(f"submitted {key} -> {file_source}", file=sys.stderr)
            if inserted:
                print("waiting for LightRAG to finish indexing …", file=sys.stderr)
                idle = await lightrag.wait_until_idle(timeout_seconds=900)
                if not idle:
                    print("LightRAG did not become idle within 900s.", file=sys.stderr)
                    exit_code = 1
                else:
                    for document, _ in inserted:
                        document.state = "indexed"
                        document.updated_at = utcnow()
                    await session.commit()
            await _update_corpus_version(session, instance)
            await session.commit()
            count = (
                await session.execute(
                    select(func.count(Document.id)).where(
                        Document.deleted.is_(False), Document.state == "indexed"
                    )
                )
            ).scalar_one()
            print(f"fixtures ready; indexed documents: {count}", file=sys.stderr)
    finally:
        await database.dispose()
    return exit_code


async def _update_corpus_version(session: AsyncSession, instance: Instance) -> None:
    docs = (
        await session.execute(
            select(Document.id, Document.version, Document.content_hash).where(
                Document.deleted.is_(False), Document.state == "indexed"
            )
        )
    ).all()
    payload = json.dumps(sorted([list(row) for row in docs]), sort_keys=True)
    instance.corpus_version = "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()
    instance.updated_at = utcnow()


async def create_key(settings: Settings, email: str, name: str) -> int:
    database = Database(settings)
    try:
        async with database.session_factory() as session:
            user = (
                await session.execute(select(User).where(User.email == email.casefold()))
            ).scalar_one_or_none()
            if user is None:
                print(f"unknown user {email}", file=sys.stderr)
                return 2
            # A role-based user has an empty explicit permission list; the key inherits
            # the effective set (role templates plus grants minus denials).
            _row, plaintext = await create_api_key(session, user=user, name=name)
            await session.commit()
            print(plaintext)
    finally:
        await database.dispose()
    return 0


async def spend(settings: Settings) -> int:
    database = Database(settings)
    try:
        async with database.session_factory() as session:
            now = utcnow()
            start = datetime(now.year, now.month, 1, tzinfo=UTC)
            rows = (
                await session.execute(
                    select(
                        UsageEvent.consumer,
                        func.count(UsageEvent.id),
                        func.coalesce(func.sum(UsageEvent.tokens_in), 0),
                        func.coalesce(func.sum(UsageEvent.tokens_out), 0),
                        func.coalesce(func.sum(UsageEvent.cost_usd), 0),
                    )
                    .where(UsageEvent.created_at >= start)
                    .group_by(UsageEvent.consumer)
                )
            ).all()
            total_cost = Decimal("0")
            print(f"usage since {start.date().isoformat()} (estimated USD)")
            for consumer, calls, tokens_in, tokens_out, cost in rows:
                total_cost += Decimal(cost)
                print(
                    f"  {consumer}: {calls} calls, {int(tokens_in)} in / {int(tokens_out)} out, "
                    f"${Decimal(cost):.6f}"
                )
            print(f"  TOTAL: ${total_cost:.6f}")
            instance = (await session.execute(select(Instance).limit(1))).scalar_one_or_none()
            if instance:
                remaining = max(Decimal("0"), Decimal(instance.monthly_budget_usd) - total_cost)
                print(
                    f"  instance budget: ${Decimal(instance.monthly_budget_usd):.2f}, "
                    f"remaining: ${remaining:.2f}"
                )
            checks = (
                await session.execute(
                    select(func.count(JobRow.id)).where(
                        JobRow.created_at >= start, JobRow.kind == "check"
                    )
                )
            ).scalar_one()
            results = (
                await session.execute(
                    select(func.count(Result.id)).where(Result.created_at >= start)
                )
            ).scalar_one()
            print(f"  checks: {checks}, results: {results}")
    finally:
        await database.dispose()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Fact Spreader Phase 1 operator CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    boot = sub.add_parser("bootstrap", help="create instance, admin, providers and models")
    boot.add_argument("--print-api-key", action="store_true")
    seed = sub.add_parser("seed-fixtures", help="approve and index the synthetic fixtures")
    seed.add_argument("--approve", action="store_true")
    key = sub.add_parser("create-api-key", help="create an API key and print it once")
    key.add_argument("--email", required=True)
    key.add_argument("--name", default="cli")
    sub.add_parser("spend", help="show the current month's usage")
    retention = sub.add_parser("retention", help="redact old contexts and clean job events")
    retention.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    if args.command == "bootstrap":
        code = asyncio.run(bootstrap(settings, print_api_key=args.print_api_key))
    elif args.command == "seed-fixtures":
        code = asyncio.run(seed_fixtures(settings, approve=args.approve))
    elif args.command == "create-api-key":
        code = asyncio.run(create_key(settings, args.email, args.name))
    elif args.command == "retention":
        code = asyncio.run(retention_job(settings, dry_run=args.dry_run))
    else:
        code = asyncio.run(spend(settings))
    raise SystemExit(code)


async def retention_job(settings: Settings, *, dry_run: bool) -> int:
    database = Database(settings)
    try:
        async with database.session_factory() as session:
            report = await run_retention(session, settings, dry_run=dry_run)
            print(report.as_dict())
            return 0
    finally:
        await database.dispose()


if __name__ == "__main__":
    main()
