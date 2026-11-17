"""Wire models for the Phase 1 public surface (PROTOCOL §3 to §4).

These classes are the contract. The API, the database serialization and the generated
OpenAPI all go through them; an ad-hoc dict in a route is a bug.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.contracts.enums import (
    JobState,
    ModerationAction,
    OutputFormat,
    ResultStatus,
    Stance,
    StatementKind,
    TurnType,
    Verdict,
)


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class TimeScope(ApiModel):
    start: date | None = Field(default=None, alias="from")
    end: date | None = Field(default=None, alias="to")
    raw: str | None = None


class Scope(ApiModel):
    subject: str | None = None
    predicate: str | None = None
    geography: str | None = None
    time_scope: TimeScope | None = None
    population: str | None = None
    quoted_source: str | None = None


class Span(ApiModel):
    start: int
    end: int
    text: str
    source: Literal["input", "context", "extracted", "ocr", "figure_description"] = "input"


class SourceQualityBasis(ApiModel):
    source: Literal[
        "document_override",
        "local_list",
        "shipped_list",
        "default_unknown",
        "peer_declared",
    ]
    list_version: str | None = None
    entry: str | None = None
    declared_grade: str | None = None
    trust_cap: str | None = None


class FigureInfo(ApiModel):
    figure_id: str
    page: int | None = None
    number: str | None = None
    image_url: str | None = None
    description_model_id: str | None = None
    editor_checked: bool = False


class Provenance(ApiModel):
    document_id: str
    document_version: int
    title: str
    publisher: str
    authors: list[str] = Field(default_factory=list)
    publication_date: date | None = None
    url: str | None = None
    doi: str | None = None
    locator: str | None = None
    dataset_id: str | None = None
    source_quality: str
    source_quality_basis: SourceQualityBasis
    domain_tags: list[str] = Field(default_factory=list)
    language: str
    license: str | None = None
    redistribution: str = "metadata_only"
    curator_organization: str | None = None
    origin_instance_id: str
    origin_document_id: str
    via_instance_id: str | None = None
    approved_at: datetime | None = None
    indexed_at: datetime | None = None
    validation: dict[str, Any] | None = None
    figure: FigureInfo | None = None


class PassageTranslation(ApiModel):
    language: str
    text: str
    machine: bool = True
    model_id: str | None = None
    created_at: datetime | None = None


class Evidence(ApiModel):
    id: str
    evidence_id: str
    passage: str
    passage_language: str
    passage_translation: PassageTranslation | None = None
    passage_hash: str
    evidence_tier: int = 1
    relevance: float = 0.0
    independence_key: str
    provenance: Provenance
    warnings: list[str] = Field(default_factory=list)


class EvidenceLink(ApiModel):
    evidence_id: str
    stance: Stance
    relevance: float = 0.0
    addresses_confounders: list[str] = Field(default_factory=list)


class WhatIsTrue(ApiModel):
    text: str
    evidence: list[str] = Field(default_factory=list)


class WhatIsMissing(ApiModel):
    text: str
    confounder: str | None = None
    evidence: list[str] = Field(default_factory=list)


class WhatIsUnverifiable(ApiModel):
    text: str
    reason: str


class GateInfo(ApiModel):
    required: int = 1
    independent_sources: int = 0
    min_quality: str = "B"
    downgraded: bool = False
    reason: str | None = None


class WarningInfo(ApiModel):
    code: str
    message: str
    statement_id: str | None = None


class Statement(ApiModel):
    id: str
    text: str
    span: Span
    kind: StatementKind
    checkworthy: bool = True
    relevance: float = 0.0
    language: str = "en"
    scope: Scope = Field(default_factory=Scope)
    topics: list[str] = Field(default_factory=list)
    domain_tags: list[str] = Field(default_factory=list)
    verdict: Verdict | None = None
    verdict_rationale: str | None = None
    evidence_links: list[EvidenceLink] = Field(default_factory=list)
    what_is_true: list[WhatIsTrue] = Field(default_factory=list)
    what_is_missing: list[WhatIsMissing] = Field(default_factory=list)
    what_is_unverifiable: list[WhatIsUnverifiable] = Field(default_factory=list)
    gate: GateInfo = Field(default_factory=GateInfo)
    relies_on_figure_description: bool = False
    warnings: list[WarningInfo] = Field(default_factory=list)
    clarification_question: str | None = None


class Contradiction(ApiModel):
    id: str
    statement_id: str
    supporting_evidence: list[str]
    refuting_evidence: list[str]
    scope_comparison: str
    detected_at: datetime


class ArgumentIssue(ApiModel):
    pattern: str
    statement_ids: list[str] = Field(default_factory=list)
    explanation: str
    evidence: list[str] = Field(default_factory=list)


class OutputModeration(ApiModel):
    checked: bool = False
    replaced: bool = False
    categories: list[str] = Field(default_factory=list)


class ModerationInfo(ApiModel):
    backend: str | None = None
    flagged: bool = False
    categories: list[str] = Field(default_factory=list)
    action: ModerationAction = ModerationAction.ALLOW
    output_moderation: OutputModeration = Field(default_factory=OutputModeration)


class PipelineInfo(ApiModel):
    software_version: str = "0.1.0"
    pipeline_version: str = "1"
    corpus_version: str
    config_hash: str
    publisher_list_version: str | None = None
    embedding_model_id: str | None = None
    models: dict[str, str] = Field(default_factory=dict)
    prompt_versions: dict[str, str] = Field(default_factory=dict)


class InputInfo(ApiModel):
    type: Literal["text", "url", "file", "image"]
    text: str
    language: str | None = None
    url: str | None = None
    file_name: str | None = None
    media_type: str | None = None
    size_bytes: int | None = None
    sha256: str | None = None
    context: dict[str, Any] | None = None


class FactCheckResult(ApiModel):
    id: str
    job_id: str
    version: int = 1
    previous_version_id: str | None = None
    status: ResultStatus
    preliminary: bool = False
    turn_type: TurnType = TurnType.NEW_CLAIM
    input: InputInfo
    detected_language: str
    response_language: str
    overall_verdict: Verdict | None = None
    overall_explanation: str | None = None
    statements: list[Statement] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)
    argument_issues: list[ArgumentIssue] = Field(default_factory=list)
    clarification_questions: list[str] = Field(default_factory=list)
    unverified_leads: list[dict[str, Any]] = Field(default_factory=list)
    moderation: ModerationInfo = Field(default_factory=ModerationInfo)
    warnings: list[WarningInfo] = Field(default_factory=list)
    pipeline: PipelineInfo
    created_at: datetime
    completed_at: datetime | None = None


class ConsistencyInfo(ApiModel):
    passed: bool
    attempts: int = 1
    fallback: bool = False
    checks: list[str] = Field(default_factory=list)


class Rendering(ApiModel):
    persona_id: str
    persona_version: int = 1
    model_id: str | None = None
    language: str
    format: str = "persona"
    text: str
    citations_used: list[str] = Field(default_factory=list)
    consistency: ConsistencyInfo
    created_at: datetime


class KeyEvidence(ApiModel):
    citation: str
    publisher: str
    publication_date: date | None = None
    url: str | None = None


class CompactReport(ApiModel):
    result_id: str
    version: int = 1
    preliminary: bool = False
    verdict: Verdict | None
    verdict_label: str
    bottom_line: str
    missing_contexts: list[str] = Field(default_factory=list)
    key_evidence: list[KeyEvidence] = Field(default_factory=list)
    report_url: str
    language: str
    warnings: list[WarningInfo] = Field(default_factory=list)


class CheckResponse(ApiModel):
    result: FactCheckResult
    rendering: Rendering | None = None
    compact: CompactReport | None = None


class Job(ApiModel):
    id: str
    kind: str = "check"
    state: JobState
    progress: float = 0.0
    result_id: str | None = None
    batch_id: str | None = None
    document_id: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    poll_after_ms: int = 800
    events_url: str
    error: dict[str, Any] | None = None


class JobAccepted(ApiModel):
    job: Job
    poll_after_ms: int = 800


class JobEnvelope(ApiModel):
    job: Job
    result: CheckResponse | None = None


class ContextMessage(RequestModel):
    role: Literal["user", "assistant", "system"]
    content: str = Field(max_length=20_000)


class CheckInput(RequestModel):
    type: Literal["text", "url", "file", "image"] = "text"
    text: str | None = None
    url: str | None = None
    language: str | None = None


class CheckRequest(RequestModel):
    input: CheckInput
    context: list[ContextMessage] = Field(default_factory=list)
    turn_type: TurnType | None = None
    mode: Literal["async", "sync"] = "async"
    fast: bool = False
    persona_id: str | None = None
    render_model_id: str | None = None
    output_format: OutputFormat = OutputFormat.SUBSTANCE
    response_language: str | None = None
    include_passages: bool = True
    domain_hint: list[str] = Field(default_factory=list)


class InstanceInfo(ApiModel):
    instance_id: str
    name: str
    organization: str | None = None
    contact: str | None = None
    protocol_version: str = "fcp/1"
    software_version: str = "0.1.0"
    setup_complete: bool
    capabilities: list[str] = Field(default_factory=list)
    corpus_version: str
    document_count: int
    supported_response_languages: list[str] = Field(default_factory=list)
    supported_corpus_languages: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    features: dict[str, bool] = Field(default_factory=dict)


class UsageMe(ApiModel):
    period: dict[str, str]
    currency: str = "USD"
    requests: dict[str, Any]
    checks: dict[str, Any]
    llm: dict[str, Any]
    limits: dict[str, Any]
    budget: dict[str, Any]
    rejected: dict[str, int]


class OpenAIModelCard(ApiModel):
    id: str
    object: str = "model"
    created: int
    owned_by: str = "fact-spreader"
    factcheck: dict[str, Any] = Field(default_factory=dict)


class OpenAIModelList(ApiModel):
    object: str = "list"
    data: list[OpenAIModelCard]


class ArchiveEntry(ApiModel):
    result_id: str
    claim_text: str
    language: str
    overall_verdict: Verdict | None = None
    topics: list[str] = Field(default_factory=list)
    domain_tags: list[str] = Field(default_factory=list)
    created_at: datetime
    preliminary: bool = False
    has_contradiction: bool = False
    submitted_by: str | None = None


class DeviceInfo(ApiModel):
    id: str
    name: str
    permissions: list[str] = Field(default_factory=list)
    created_at: datetime
    last_seen_at: datetime | None = None
    revoked_at: datetime | None = None


class DeviceCreated(ApiModel):
    device: DeviceInfo
    token: str


class DeviceCreate(RequestModel):
    name: str = Field(min_length=1, max_length=200)
    permissions: list[str] = Field(default_factory=lambda: ["claims:submit"])


class FeedbackRequest(RequestModel):
    kind: Literal["helpful", "unhelpful", "incorrect"]
    comment: str | None = Field(default=None, max_length=500)
