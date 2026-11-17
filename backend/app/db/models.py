"""Database models for the Phase 1 vertical slice.

Nested result payloads are JSONB because a result is an immutable, versioned document
(DECISIONS.md D7). Configuration, provenance, jobs, usage and audit rows are relational so
the queries that matter now are plain SQL.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pgvector.sqlalchemy import Vector  # type: ignore[import-untyped]
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Instance(Base):
    __tablename__ = "instance"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), default="Fact Spreader")
    organization: Mapped[str | None] = mapped_column(String(200))
    contact: Mapped[str | None] = mapped_column(String(200))
    setup_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    overview_public: Mapped[bool] = mapped_column(Boolean, default=False)
    corpus_version: Mapped[str] = mapped_column(String(80), default="sha256:empty")
    monthly_budget_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), default=Decimal("15.000000")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(255))
    permissions: Mapped[list[str]] = mapped_column(JSONB, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    totp_secret_enc: Mapped[bytes | None] = mapped_column()
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    llm_budget_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal("15.000000"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SessionToken(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(500))
    ip_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(lazy="joined")


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    key_prefix: Mapped[str] = mapped_column(String(24))
    permissions: Mapped[list[str]] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DeviceToken(Base):
    __tablename__ = "device_tokens"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    token_prefix: Mapped[str] = mapped_column(String(24))
    permissions: Mapped[list[str]] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Feedback(Base):
    __tablename__ = "feedback"
    __table_args__ = (UniqueConstraint("result_id", "user_id", name="uq_feedback_result_user"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    result_id: Mapped[str] = mapped_column(ForeignKey("results.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20))
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Provider(Base):
    __tablename__ = "providers"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(40), default="openai_compatible")
    base_url: Mapped[str] = mapped_column(String(500))
    api_key_enc: Mapped[bytes | None] = mapped_column()
    is_local: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ModelRecord(Base):
    __tablename__ = "models"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider_id: Mapped[str] = mapped_column(
        ForeignKey("providers.id", ondelete="CASCADE"), index=True
    )
    gateway_alias: Mapped[str] = mapped_column(String(80), unique=True)
    model_name: Mapped[str] = mapped_column(String(200))
    capabilities: Mapped[list[str]] = mapped_column(JSONB, default=list)
    context_window: Mapped[int | None] = mapped_column(Integer)
    embedding_dim: Mapped[int | None] = mapped_column(Integer)
    multilingual: Mapped[bool] = mapped_column(Boolean, default=False)
    is_local: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    input_cost_per_mtok: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal("0"))
    output_cost_per_mtok: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    provider: Mapped[Provider] = relationship(lazy="joined")


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(500))
    publisher: Mapped[str] = mapped_column(String(300))
    authors: Mapped[list[str]] = mapped_column(JSONB, default=list)
    publication_date: Mapped[date | None] = mapped_column(Date)
    url: Mapped[str | None] = mapped_column(String(2000))
    doi: Mapped[str | None] = mapped_column(String(300))
    dataset_id: Mapped[str | None] = mapped_column(String(300))
    source_quality: Mapped[str] = mapped_column(String(1), default="D")
    source_quality_basis: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    domain_tags: Mapped[list[str]] = mapped_column(JSONB, default=list)
    language: Mapped[str] = mapped_column(String(16), default="en")
    license: Mapped[str | None] = mapped_column(String(200))
    redistribution: Mapped[str] = mapped_column(String(40), default="metadata_only")
    origin_instance_id: Mapped[str] = mapped_column(String(64))
    origin_document_id: Mapped[str] = mapped_column(String(64))
    content_hash: Mapped[str] = mapped_column(String(80))
    state: Mapped[str] = mapped_column(String(30), default="received", index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    submitted_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    approved_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    versions: Mapped[list[DocumentVersion]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (UniqueConstraint("document_id", "version", name="uq_document_version"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(80))
    content_md: Mapped[str] = mapped_column(Text)
    file_path: Mapped[str | None] = mapped_column(String(1000))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    document: Mapped[Document] = relationship(back_populates="versions")
    passages: Mapped[list[Passage]] = relationship(
        back_populates="document_version", cascade="all, delete-orphan"
    )


class Passage(Base):
    __tablename__ = "passages"
    __table_args__ = (
        UniqueConstraint("document_version_id", "content_hash", name="uq_passage_version_hash"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_version_id: Mapped[str] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"), index=True
    )
    content_hash: Mapped[str] = mapped_column(String(80))
    text: Mapped[str] = mapped_column(Text)
    locator: Mapped[str | None] = mapped_column(String(300))
    figure_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    document_version: Mapped[DocumentVersion] = relationship(back_populates="passages")


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_state_created", "state", "created_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(40), default="check")
    state: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    result_id: Mapped[str | None] = mapped_column(String(64), index=True)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_by: Mapped[str | None] = mapped_column(String(100))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ClaimCache(Base):
    """Semantic fast-mode cache over normalized claims.

    The embedding is the corpus embedding model's vector; a hit is only valid for the
    same corpus version. The row points at the full result it may serve.
    """

    __tablename__ = "claim_cache"
    __table_args__ = (Index("ix_claim_cache_corpus", "corpus_version"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    normalized_text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(1024))
    result_id: Mapped[str] = mapped_column(ForeignKey("results.id", ondelete="CASCADE"), index=True)
    corpus_version: Mapped[str] = mapped_column(String(80))
    language: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Result(Base):
    __tablename__ = "results"
    __table_args__ = (Index("ix_results_created", "created_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    previous_result_id: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(30), default="complete")
    preliminary: Mapped[bool] = mapped_column(Boolean, default=False)
    turn_type: Mapped[str] = mapped_column(String(40), default="new_claim")
    input: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    detected_language: Mapped[str] = mapped_column(String(16), default="en")
    response_language: Mapped[str] = mapped_column(String(16), default="en")
    overall_verdict: Mapped[str | None] = mapped_column(String(40), index=True)
    overall_explanation: Mapped[str | None] = mapped_column(Text)
    statements: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    contradictions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    argument_issues: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    clarification_questions: Mapped[list[str]] = mapped_column(JSONB, default=list)
    warnings: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    moderation: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    renderings: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    pipeline: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)


class JobEvent(Base):
    __tablename__ = "job_events"
    __table_args__ = (UniqueConstraint("job_id", "seq", name="uq_job_event_seq"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(40))
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class UsageEvent(Base):
    __tablename__ = "usage_events"
    __table_args__ = (Index("ix_usage_created_consumer", "created_at", "consumer"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    request_id: Mapped[str | None] = mapped_column(String(80), index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True)
    api_key_id: Mapped[str | None] = mapped_column(String(64))
    consumer: Mapped[str] = mapped_column(String(40))
    role: Mapped[str] = mapped_column(String(40))
    provider: Mapped[str] = mapped_column(String(100))
    model: Mapped[str] = mapped_column(String(200))
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal("0"))
    cost_estimated: Mapped[bool] = mapped_column(Boolean, default=False)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[int] = mapped_column(Integer, default=200)
    data_classes: Mapped[list[str]] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ModerationEvent(Base):
    __tablename__ = "moderation_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    result_id: Mapped[str | None] = mapped_column(String(64), index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    flagged: Mapped[bool] = mapped_column(Boolean, default=False)
    categories: Mapped[list[str]] = mapped_column(JSONB, default=list)
    action: Mapped[str] = mapped_column(String(20), default="allow")
    output_replaced: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CorpusGap(Base):
    __tablename__ = "corpus_gaps"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    normalized_topic: Mapped[str] = mapped_column(String(300), unique=True, index=True)
    query: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(16), default="en")
    topics: Mapped[list[str]] = mapped_column(JSONB, default=list)
    frequency: Mapped[int] = mapped_column(Integer, default=1)
    sample_result_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    state: Mapped[str] = mapped_column(String(20), default="open")
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ContradictionRecord(Base):
    __tablename__ = "contradictions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    statement_text: Mapped[str] = mapped_column(Text)
    result_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    supporting: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    refuting: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    state: Mapped[str] = mapped_column(String(20), default="open")
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (UniqueConstraint("principal_id", "key", name="uq_idempotency_principal_key"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    principal_id: Mapped[str] = mapped_column(String(80), index=True)
    key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(80))
    status_code: Mapped[int] = mapped_column(Integer)
    response: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    actor_id: Mapped[str | None] = mapped_column(String(64), index=True)
    actor_type: Mapped[str] = mapped_column(String(30), default="user")
    action: Mapped[str] = mapped_column(String(80))
    object_type: Mapped[str | None] = mapped_column(String(60))
    object_id: Mapped[str | None] = mapped_column(String(64))
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
