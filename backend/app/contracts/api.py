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
    withdrawn: bool = False


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


class SetupStatus(ApiModel):
    started: bool
    complete: bool
    setup_token_required: bool
    steps: dict[str, bool] = Field(default_factory=dict)
    next_step: str | None = None
    instance: dict[str, Any] | None = None


class SetupAdminRequest(RequestModel):
    token: str = Field(min_length=1, max_length=200)
    email: str = Field(min_length=5, max_length=320)
    password: str = Field(min_length=1, max_length=500)
    display_name: str = Field(min_length=1, max_length=200)


class SetupAdminCreated(ApiModel):
    user_id: str
    email: str
    totp_secret: str
    provisioning_uri: str


class SetupTotpRequest(RequestModel):
    token: str = Field(min_length=1, max_length=200)
    code: str = Field(min_length=6, max_length=64)


class SetupTotpConfirmed(ApiModel):
    recovery_codes: list[str]


class SetupOrganizationRequest(RequestModel):
    name: str = Field(min_length=1, max_length=200)
    organization: str | None = Field(default=None, max_length=200)
    contact: str | None = Field(default=None, max_length=200)
    overview_public: bool = False
    monthly_budget_usd: float | None = Field(default=None, gt=0, le=1_000_000)


class SetupProviderRequest(RequestModel):
    name: str = Field(min_length=1, max_length=200)
    base_url: str = Field(min_length=8, max_length=500)
    api_key: str | None = Field(default=None, max_length=500)
    is_local: bool = False
    use: Literal["chat", "embedding"] = "chat"


class SetupProviderTested(ApiModel):
    provider_id: str
    models: list[str] = Field(default_factory=list)
    tested_at: datetime


class SetupModelsRequest(RequestModel):
    chat_model: str = Field(min_length=1, max_length=200)
    embedding_model: str = Field(min_length=1, max_length=200)
    embedding_dim: int | None = Field(default=None, ge=1, le=8192)
    multilingual: bool = True


class SetupModelsAssigned(ApiModel):
    aliases: list[str]
    chat_model: str
    embedding_model: str


class SetupModerationTest(ApiModel):
    backend: str
    flagged: bool
    categories: list[str] = Field(default_factory=list)


class SetupCompleted(ApiModel):
    complete: bool
    instance_id: str


class ProviderInfo(ApiModel):
    id: str
    name: str
    base_url: str
    is_local: bool
    enabled: bool
    has_key: bool
    created_at: datetime


class ProviderCreate(RequestModel):
    name: str = Field(min_length=1, max_length=200)
    base_url: str = Field(min_length=8, max_length=500)
    api_key: str | None = Field(default=None, max_length=500)
    is_local: bool = False
    test_connection: bool = True


class ProviderUpdate(RequestModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    base_url: str | None = Field(default=None, min_length=8, max_length=500)
    api_key: str | None = Field(default=None, max_length=500)
    is_local: bool | None = None
    enabled: bool | None = None


class ProviderCreated(ApiModel):
    provider: ProviderInfo
    models: list[str] = Field(default_factory=list)


class ProviderTestResult(ApiModel):
    provider_id: str
    reachable: bool
    models: list[str] = Field(default_factory=list)
    latency_ms: int = 0


class ModelInfo(ApiModel):
    id: str
    provider_id: str
    model_name: str
    gateway_alias: str | None = None
    source_model_id: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    tested_capabilities: list[str] = Field(default_factory=list)
    context_window: int | None = None
    embedding_dim: int | None = None
    multilingual: bool = False
    is_local: bool = False
    enabled: bool = True
    input_cost_per_mtok: float = 0.0
    output_cost_per_mtok: float = 0.0
    created_at: datetime


class ModelCreate(RequestModel):
    provider_id: str = Field(min_length=1, max_length=64)
    model_name: str = Field(min_length=1, max_length=200)
    capabilities: list[str] = Field(default_factory=list)
    context_window: int | None = Field(default=None, ge=1)
    embedding_dim: int | None = Field(default=None, ge=1, le=8192)
    multilingual: bool = False
    input_cost_per_mtok: float = Field(default=0.0, ge=0)
    output_cost_per_mtok: float = Field(default=0.0, ge=0)


class ModelUpdate(RequestModel):
    capabilities: list[str] | None = None
    context_window: int | None = Field(default=None, ge=1)
    embedding_dim: int | None = Field(default=None, ge=1, le=8192)
    multilingual: bool | None = None
    enabled: bool | None = None
    input_cost_per_mtok: float | None = Field(default=None, ge=0)
    output_cost_per_mtok: float | None = Field(default=None, ge=0)


class CapabilityProbeRequest(RequestModel):
    capabilities: list[str] = Field(default_factory=list)


class CapabilityTestInfo(ApiModel):
    capability: str
    status: str
    detail: str = ""
    dimension: int | None = None
    latency_ms: int = 0
    tested_at: datetime


class CapabilityProbeReport(ApiModel):
    model_id: str
    results: list[CapabilityTestInfo] = Field(default_factory=list)


class RoleInfo(ApiModel):
    alias: str
    label: str
    required_capabilities: list[str] = Field(default_factory=list)
    min_context: int | None = None
    multilingual: bool = False
    embedding_dim: int | None = None
    model: ModelInfo | None = None
    suitable: bool = False
    reasons: list[str] = Field(default_factory=list)


class RoleAssignment(ApiModel):
    model_id: str = Field(min_length=1, max_length=64)


class DataFlowPolicy(ApiModel):
    allow_external: bool = True
    fallback_alias: str | None = None


class PublisherOverride(RequestModel):
    key: str = Field(min_length=1, max_length=200)
    grade: Literal["A", "B", "C", "D"] | None = None
    disputed: bool | None = None
    note: str | None = Field(default=None, max_length=300)


class PublisherOverridesRequest(RequestModel):
    entries: list[PublisherOverride] = Field(default_factory=list)


class PublisherEntryInfo(ApiModel):
    key: str
    publisher: str | None = None
    grade: str
    disputed: bool = False
    overridden: bool = False


class PublisherListInfo(ApiModel):
    version: str
    effective_version: str
    entries: list[PublisherEntryInfo] = Field(default_factory=list)
    overrides: list[dict[str, Any]] = Field(default_factory=list)


class PublisherDiffEntry(ApiModel):
    key: str
    publisher: str | None = None
    field: str
    shipped: Any = None
    local: Any = None


class PublisherResolveRequest(RequestModel):
    publisher: str | None = Field(default=None, max_length=300)
    url: str | None = Field(default=None, max_length=2000)
    doi: str | None = Field(default=None, max_length=300)


class PublisherResolveResponse(ApiModel):
    grade: str
    basis: SourceQualityBasis
    effective_version: str


class PublisherImpactEntry(ApiModel):
    cache_id: str
    result_id: str
    created_at: str
    publishers: list[str] = Field(default_factory=list)


class UsageSummary(ApiModel):
    period: dict[str, str]
    currency: str = "USD"
    totals: dict[str, Any]
    cards: dict[str, int] = Field(default_factory=dict)
    series: list[dict[str, Any]] = Field(default_factory=list)
    breakdowns: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)


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


class RecheckRequest(RequestModel):
    reason: Literal["corpus_changed", "manual"] = "manual"
    fast: bool = False


class FeedbackRequest(RequestModel):
    kind: Literal["helpful", "unhelpful", "incorrect"]
    comment: str | None = Field(default=None, max_length=500)


class ResearchFilters(RequestModel):
    start: date | None = Field(default=None, alias="from")
    end: date | None = Field(default=None, alias="to")
    domains: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    min_source_quality: str | None = None


class ResearchRequest(RequestModel):
    query: str = Field(min_length=1, max_length=2000)
    response_language: str | None = None
    filters: ResearchFilters = Field(default_factory=ResearchFilters)
    summary: bool = False
    limit: int = Field(default=20, ge=1, le=50)


class ResearchPassage(ApiModel):
    evidence_id: str
    passage: str
    passage_language: str
    passage_translation: PassageTranslation | None = None
    locator: str | None = None
    score: float = 0.0
    figure: FigureInfo | None = None


class ResearchDocumentSummary(ApiModel):
    id: str
    title: str
    publisher: str
    publication_date: date | None = None
    source_quality: str
    language: str
    url: str | None = None
    license: str | None = None
    redistribution: str = "metadata_only"


class ResearchDocument(ApiModel):
    document: ResearchDocumentSummary
    passages: list[ResearchPassage] = Field(default_factory=list)


class ResearchClaim(ApiModel):
    result_id: str
    claim_text: str
    verdict: Verdict | None = None
    created_at: datetime
    excerpt: str = ""


class SummaryCitation(ApiModel):
    sentence: int
    evidence_ids: list[str] = Field(default_factory=list)


class ResearchSummary(ApiModel):
    text: str
    language: str
    citations: list[SummaryCitation] = Field(default_factory=list)
    consistency: ConsistencyInfo
    model_id: str | None = None
    created_at: datetime


class ResearchResponse(ApiModel):
    query: str
    detected_language: str
    response_language: str
    documents: list[ResearchDocument] = Field(default_factory=list)
    claims: list[ResearchClaim] = Field(default_factory=list)
    summary: ResearchSummary | None = None
    warnings: list[WarningInfo] = Field(default_factory=list)
    took_ms: int = 0
    gaps_recorded: bool = False


class DocumentWarning(ApiModel):
    code: str
    message: str


class DocumentFigure(ApiModel):
    id: str
    page: int | None = None
    number: str | None = None
    caption: str | None = None
    description: str | None = None
    description_source: str = "vision"
    description_model_id: str | None = None
    editor_checked: bool = False
    editor_checked_by: str | None = None
    created_at: datetime | None = None
    image_url: str | None = None


class DocumentApproval(ApiModel):
    approved_at: datetime
    approved_by: str
    note: str | None = None


class DocumentInfo(ApiModel):
    id: str
    version: int = 1
    content_hash: str
    title: str
    publisher: str
    authors: list[str] = Field(default_factory=list)
    publication_date: date | None = None
    url: str | None = None
    doi: str | None = None
    dataset_id: str | None = None
    source_quality: str
    source_quality_basis: dict[str, Any] = Field(default_factory=dict)
    domain_tags: list[str] = Field(default_factory=list)
    language: str
    license: str | None = None
    redistribution: str = "metadata_only"
    curator_organization: str | None = None
    origin_instance_id: str
    origin_document_id: str
    provenance_chain: list[dict[str, Any]] = Field(default_factory=list)
    content_type: str = "text/markdown"
    size_bytes: int = 0
    state: str
    warnings: list[DocumentWarning] = Field(default_factory=list)
    duplicate_of: str | None = None
    submitted_by: str | None = None
    approval: DocumentApproval | None = None
    figures: list[DocumentFigure] = Field(default_factory=list)
    approval_preselected: bool = False
    created_at: datetime
    updated_at: datetime
    deleted: bool = False


class DocumentMetadata(RequestModel):
    title: str | None = None
    publisher: str | None = None
    authors: list[str] = Field(default_factory=list)
    publication_date: date | None = None
    url: str | None = None
    doi: str | None = None
    dataset_id: str | None = None
    license: str | None = None
    redistribution: str | None = None
    domain_tags: list[str] = Field(default_factory=list)
    language: str | None = None
    source_quality_override: str | None = None


class DocumentSubmitRequest(RequestModel):
    input: CheckInput
    metadata: DocumentMetadata = Field(default_factory=DocumentMetadata)
    batch_id: str | None = None
    force: bool = False


class DocumentEstimate(ApiModel):
    pages: int = 0
    figures: int = 0
    vision_calls: int = 0
    estimated_usd: float = 0.0
    exceeds_budget: bool = False


class DocumentSubmitResponse(ApiModel):
    document: DocumentInfo
    job: Job
    estimate: DocumentEstimate
    duplicate_of: str | None = None


class ApprovalRequest(RequestModel):
    license_confirmed: bool = False
    redistribution: Literal["full_text", "excerpts_only", "metadata_only"]
    note: str | None = None


class RejectRequest(RequestModel):
    reason: str = Field(min_length=1, max_length=1000)


class WithdrawRequest(RequestModel):
    reason: str = Field(min_length=1, max_length=1000)


class FigureUpdateRequest(RequestModel):
    description: str = Field(min_length=1, max_length=5000)


class ReviewQueueResponse(ApiModel):
    data: list[DocumentInfo] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)
    summary: dict[str, Any] = Field(default_factory=dict)


class EditorContradiction(ApiModel):
    id: str
    statement_text: str
    result_ids: list[str] = Field(default_factory=list)
    supporting: list[dict[str, Any]] = Field(default_factory=list)
    refuting: list[dict[str, Any]] = Field(default_factory=list)
    state: str
    detected_at: datetime


class EditorGap(ApiModel):
    id: str
    normalized_topic: str
    query: str
    language: str
    topics: list[str] = Field(default_factory=list)
    frequency: int
    sample_result_ids: list[str] = Field(default_factory=list)
    state: str
    first_seen: datetime
    last_seen: datetime


class EditorStateRequest(RequestModel):
    state: str


class BatchCounts(ApiModel):
    total: int = 0
    ready: int = 0
    warning: int = 0
    duplicate: int = 0
    failed: int = 0


class BatchFile(ApiModel):
    document_id: str
    filename: str
    state: str
    warnings: list[DocumentWarning] = Field(default_factory=list)


class BatchInfo(ApiModel):
    id: str
    state: str
    counts: BatchCounts
    estimated_usd: float = 0.0
    actual_usd: float = 0.0
    budget_remaining_usd: float | None = None
    files: list[BatchFile] = Field(default_factory=list)
    warnings: list[DocumentWarning] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class BatchResponse(ApiModel):
    batch: BatchInfo


class BatchSubmitRequest(RequestModel):
    metadata: DocumentMetadata = Field(default_factory=DocumentMetadata)
    overrides: dict[str, DocumentMetadata] = Field(default_factory=dict)
    urls: list[str] = Field(default_factory=list, max_length=100)
    force: bool = False
    accept_estimate: bool = False


class BatchActionRequest(RequestModel):
    document_ids: list[str] = Field(default_factory=list)
    license_confirmed: bool = False
    redistribution: Literal["full_text", "excerpts_only", "metadata_only"] = "metadata_only"
    note: str | None = None


class BatchRejectRequest(RequestModel):
    document_ids: list[str] = Field(default_factory=list)
    reason: str = Field(min_length=1, max_length=1000)


class GapRecheckRequest(RequestModel):
    limit: int = Field(default=10, ge=1, le=50)


class BatchRetryRequest(RequestModel):
    document_ids: list[str] = Field(default_factory=list)


class UserInfo(ApiModel):
    id: str
    email: str
    display_name: str
    roles: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    effective_permissions: list[str] = Field(default_factory=list)
    denied_permissions: list[str] = Field(default_factory=list)
    requests_per_day: int | None = None
    text_chars: int | None = None
    max_file_bytes: int | None = None
    max_batch_files: int | None = None
    is_active: bool = True
    totp_enabled: bool = False


class UserCreateRequest(RequestModel):
    email: str = Field(min_length=3, max_length=320)
    display_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=8, max_length=500)
    roles: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)


class UserPasswordResetRequest(RequestModel):
    password: str = Field(min_length=1, max_length=500)


class UserUpdateRequest(RequestModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    roles: list[str] | None = None
    permissions: list[str] | None = None
    denied_permissions: list[str] | None = None
    requests_per_day: int | None = None
    text_chars: int | None = None
    max_file_bytes: int | None = None
    max_batch_files: int | None = None
    is_active: bool | None = None
