"""The check pipeline: extract → retrieve → verify/audit → gate → deterministic substance.

The model never writes the final verdict object. Verification returns structured
proposals; this module validates against the retrieved evidence, applies the pure gate,
detects contradictions, computes the overall verdict and builds the report.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.api import (
    ArgumentIssue,
    CompactReport,
    Contradiction,
    Evidence,
    EvidenceLink,
    FactCheckResult,
    InputInfo,
    ModerationInfo,
    PipelineInfo,
    Provenance,
    SourceQualityBasis,
    Statement,
    WarningInfo,
    WhatIsMissing,
    WhatIsTrue,
    WhatIsUnverifiable,
)
from app.contracts.enums import Stance, TurnType, Verdict
from app.core.config import Settings
from app.core.ids import new_id, normalize_text, sha256_text, utcnow
from app.db.models import (
    ContradictionRecord,
    CorpusGap,
    Document,
    DocumentVersion,
    Instance,
    Passage,
)
from app.llm.aliases import FS_AUDIT, FS_EXTRACT, FS_MODERATION, FS_VERIFY
from app.llm.client import StructuredLLM
from app.pipeline.compact import build_compact
from app.pipeline.extraction import ExtractionResult, extract_statements
from app.pipeline.gate import GateConfig, gate_statement, overall_verdict
from app.pipeline.verification import VerificationProposal, verify_statement
from app.retrieval.lightrag import LightRAGClient, LightRAGError, RetrievalChunk
from app.services.language import LanguageService
from app.services.methodology import Methodology
from app.services.publishers import PublisherRegistry
from app.services.templates import (
    overall_explanation,
    refusal_text,
    unsupported_language_notice,
)

logger = logging.getLogger(__name__)

PIPELINE_VERSION = "1"
_CONFOUNDER_TOPICS = {
    "crime_statistics": {"racism", "politics"},
    "labor_statistics": {"economics", "poverty"},
}


class PipelineError(RuntimeError):
    def __init__(self, code: str, detail: str, *, retryable: bool = False) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.retryable = retryable


@dataclass
class PipelineOutcome:
    result: FactCheckResult
    compact: CompactReport
    gap_query: str | None = None
    no_matching_document: bool = False


@dataclass
class _EvidencePool:
    by_hash: dict[str, Evidence] = field(default_factory=dict)
    by_id: dict[str, Evidence] = field(default_factory=dict)
    next_index: int = 1


class CheckPipeline:
    def __init__(
        self,
        *,
        settings: Settings,
        llm: StructuredLLM,
        lightrag: LightRAGClient,
        publishers: PublisherRegistry,
        methodology: Methodology,
        language: LanguageService,
        session: AsyncSession,
        instance: Instance,
    ) -> None:
        self.settings = settings
        self.llm = llm
        self.lightrag = lightrag
        self.publishers = publishers
        self.methodology = methodology
        self.language = language
        self.session = session
        self.instance = instance

    async def run(
        self,
        *,
        result_id: str,
        job_id: str,
        user_id: str | None,
        text: str,
        response_language: str | None,
        turn_type: TurnType,
        moderation: ModerationInfo,
        source_url: str | None = None,
    ) -> PipelineOutcome:
        started = utcnow()
        normalized = normalize_text(text)
        decision = self.language.resolve(normalized, response_language)
        warnings: list[WarningInfo] = []
        if decision.unsupported:
            warnings.append(
                WarningInfo(
                    code="unsupported_language",
                    message=unsupported_language_notice(decision.response),
                )
            )

        extraction = await extract_statements(
            self.llm,
            text=normalized,
            language=decision.detected,
            topics=list(self.methodology.checklists),
            domain_tags=sorted(
                {
                    tag
                    for checklist in self.methodology.checklists.values()
                    for tag in checklist.domain_tags
                }
            ),
            user_id=user_id,
        )
        if extraction.skipped:
            warnings.append(
                WarningInfo(
                    code="parse_warning",
                    message="The extractor returned statements whose spans could not be located.",
                )
            )
        if extraction.statements and not any(s.checkworthy for s in extraction.statements):
            warnings.append(
                WarningInfo(
                    code="audit_incomplete",
                    message="Only non-checkable statements were extracted.",
                )
            )

        statements: list[Statement] = []
        pool = _EvidencePool()
        argument_issues: list[ArgumentIssue] = []
        contradictions: list[Contradiction] = []
        contradiction_rows: list[ContradictionRecord] = []
        any_checkworthy = False
        any_matching = False

        for index, located in enumerate(extraction.statements, start=1):
            statement_id = f"S{index}"
            if not located.checkworthy:
                statements.append(
                    Statement(
                        id=statement_id,
                        text=located.text,
                        span=located.span,
                        kind=located.kind,
                        checkworthy=False,
                        relevance=located.relevance,
                        language=decision.detected,
                        scope=located.scope,
                        topics=located.topics,
                        domain_tags=located.domain_tags,
                    )
                )
                continue
            any_checkworthy = True
            topics = located.topics or self._infer_topics(located.domain_tags)
            confounders = self.methodology.confounders_for(topics)
            staleness_days = self.methodology.staleness_days_for(topics)
            try:
                retrieval = await self.lightrag.query_data(
                    _retrieval_query(located.text, extraction, located.keywords_low),
                    high_level_keywords=_dedupe(
                        [*extraction.keywords_high, *located.keywords_high]
                    )[:8],
                    low_level_keywords=_dedupe([*extraction.keywords_low, *located.keywords_low])[
                        :16
                    ],
                )
            except LightRAGError as exc:
                raise PipelineError(
                    "retrieval_unavailable",
                    f"The retrieval service failed: {exc}",
                    retryable=True,
                ) from exc
            candidates = await self._candidates(
                retrieval.chunks,
                pool=pool,
                statement_text=located.text,
            )
            if candidates:
                any_matching = True
                proposal = await verify_statement(
                    self.llm,
                    statement_text=located.text,
                    statement_scope=located.scope,
                    topics=topics,
                    candidates=candidates,
                    confounders=confounders,
                    methodology=self.methodology,
                    staleness_days=staleness_days,
                    user_id=user_id,
                )
            else:
                proposal = VerificationProposal(
                    verdict=Verdict.INSUFFICIENT_EVIDENCE,
                    rationale="No approved passage matched this statement.",
                    links=[],
                    what_is_true=[],
                    what_is_missing=[],
                    what_is_unverifiable=[],
                    argument_issues=[],
                    audit_complete=False,
                    warnings=["no_matching_document"],
                )
                warnings.append(
                    WarningInfo(
                        code="no_matching_document",
                        message="No approved document matched a statement.",
                        statement_id=statement_id,
                    )
                )
            time_start = located.scope.time_scope.start if located.scope.time_scope else None
            time_end = located.scope.time_scope.end if located.scope.time_scope else None
            decision_gate = gate_statement(
                proposal,
                evidence_by_id={item.id: item for item in pool.by_id.values()},
                time_scope_start=time_start,
                time_scope_end=time_end,
                config=GateConfig(
                    required=1,
                    min_quality="B",
                    staleness_days=staleness_days,
                ),
            )
            statement_warnings = list(decision_gate.warnings)
            for code in proposal.warnings:
                if code == "no_matching_document":
                    continue
                statement_warnings.append(WarningInfo(code=code, message=code.replace("_", " ")))
            statement_warnings = _dedupe_warnings(statement_warnings)
            statement = self._build_statement(
                statement_id=statement_id,
                located=located,
                language=decision.detected,
                proposal=proposal,
                gate=decision_gate,
                warnings=statement_warnings,
                evidence_by_id={item.id: item for item in pool.by_id.values()},
            )
            statements.append(statement)
            warnings.extend(
                warning.model_copy(update={"statement_id": statement_id})
                for warning in decision_gate.warnings
            )
            for issue in proposal.argument_issues:
                argument_issues.append(
                    ArgumentIssue(
                        pattern=issue.pattern,
                        statement_ids=[statement_id],
                        explanation=issue.explanation,
                        evidence=issue.evidence,
                    )
                )
            if decision_gate.contradiction is not None:
                contradiction_id = new_id("ctr")
                contradictions.append(
                    Contradiction(
                        id=contradiction_id,
                        statement_id=statement_id,
                        supporting_evidence=decision_gate.contradiction.supporting_evidence,
                        refuting_evidence=decision_gate.contradiction.refuting_evidence,
                        scope_comparison=decision_gate.contradiction.scope_comparison,
                        detected_at=utcnow(),
                    )
                )
                contradiction_rows.append(
                    ContradictionRecord(
                        id=contradiction_id,
                        statement_text=located.text,
                        result_ids=[result_id],
                        supporting=_evidence_refs(
                            decision_gate.contradiction.supporting_evidence, pool.by_id
                        ),
                        refuting=_evidence_refs(
                            decision_gate.contradiction.refuting_evidence, pool.by_id
                        ),
                        state="open",
                        detected_at=utcnow(),
                    )
                )

        overall = overall_verdict([statement.verdict for statement in statements])
        if not any_checkworthy:
            overall = Verdict.NOT_CHECKABLE
        explanation = overall_explanation(overall, decision.response)
        if not any_checkworthy:
            explanation = overall_explanation(Verdict.NOT_CHECKABLE, decision.response)
        if not any_matching and any_checkworthy:
            warnings.append(
                WarningInfo(
                    code="no_matching_document",
                    message="No approved document matched this input.",
                )
            )
        warnings = _dedupe_warnings(warnings)
        cited_ids = _cited_evidence_ids(statements)
        evidence = [pool.by_id[eid] for eid in cited_ids if eid in pool.by_id]
        result = FactCheckResult(
            id=result_id,
            job_id=job_id,
            version=1,
            status="complete",
            preliminary=False,
            turn_type=turn_type,
            input=InputInfo(
                type="url" if source_url else "text",
                text=normalized,
                language=decision.detected,
                url=source_url,
                sha256=sha256_text(normalized),
            ),
            detected_language=decision.detected,
            response_language=decision.response,
            overall_verdict=overall,
            overall_explanation=explanation,
            statements=statements,
            evidence=evidence,
            contradictions=contradictions,
            argument_issues=_dedupe_issues(argument_issues),
            clarification_questions=[],
            moderation=moderation,
            warnings=warnings,
            pipeline=self._pipeline_info(),
            created_at=started,
            completed_at=utcnow(),
        )
        gap_query: str | None = None
        if any_checkworthy and not any_matching:
            gap_query = normalized
            await self._upsert_gap(
                query=normalized,
                language=decision.detected,
                topics=extraction.topics,
                result_id=result_id,
            )
        for row in contradiction_rows:
            self.session.add(row)
        compact = build_compact(result)
        return PipelineOutcome(
            result=result,
            compact=compact,
            gap_query=gap_query,
            no_matching_document=not any_matching and any_checkworthy,
        )

    def _build_statement(
        self,
        *,
        statement_id: str,
        located: Any,
        language: str,
        proposal: VerificationProposal,
        gate: Any,
        warnings: list[WarningInfo],
        evidence_by_id: dict[str, Evidence],
    ) -> Statement:
        links = [
            EvidenceLink(
                evidence_id=link.id,
                stance=Stance(link.stance),
                relevance=link.relevance,
                addresses_confounders=link.addresses_confounders,
            )
            for link in proposal.links
        ]
        true_items = [
            WhatIsTrue(text=item.text, evidence=item.evidence) for item in proposal.what_is_true
        ]
        missing_items = [
            WhatIsMissing(text=item.text, confounder=item.confounder, evidence=item.evidence)
            for item in proposal.what_is_missing
        ]
        unverifiable = [
            WhatIsUnverifiable(text=item.text, reason=item.reason)
            for item in proposal.what_is_unverifiable
        ]
        if gate.gate.downgraded:
            true_items = []
            for item in missing_items:
                unverifiable.append(
                    WhatIsUnverifiable(
                        text=item.text,
                        reason="audit_incomplete"
                        if gate.gate.reason == "audit_incomplete"
                        else "other",
                    )
                )
            missing_items = []
            unverifiable.append(
                WhatIsUnverifiable(
                    text="A source was found, but it did not meet the evidence gate.",
                    reason="other",
                )
            )
        figure_dependent = any(
            (figure := evidence_by_id[link.evidence_id].provenance.figure) is not None
            and not figure.editor_checked
            for link in links
            if link.evidence_id in evidence_by_id
        )
        return Statement(
            id=statement_id,
            text=located.text,
            span=located.span,
            kind=located.kind,
            checkworthy=located.checkworthy,
            relevance=located.relevance,
            language=language,
            scope=located.scope,
            topics=located.topics,
            domain_tags=located.domain_tags,
            verdict=gate.verdict,
            verdict_rationale=proposal.rationale,
            evidence_links=links,
            what_is_true=true_items,
            what_is_missing=missing_items,
            what_is_unverifiable=unverifiable,
            gate=gate.gate,
            relies_on_figure_description=figure_dependent,
            warnings=warnings,
        )

    def _infer_topics(self, domain_tags: list[str]) -> list[str]:
        inferred: list[str] = []
        for topic, tags in _CONFOUNDER_TOPICS.items():
            if set(tags) & set(domain_tags):
                inferred.append(topic)
        return inferred

    async def _candidates(
        self,
        chunks: list[RetrievalChunk],
        *,
        pool: _EvidencePool,
        statement_text: str,
    ) -> list[Evidence]:
        candidates: list[Evidence] = []
        seen_keys: set[str] = set()
        for chunk in chunks:
            match = _FILE_SOURCE_RE.search(chunk.file_path or "")
            if match is None:
                continue
            document_id, version_text = match.group(1), match.group(2)
            row = (
                await self.session.execute(
                    select(DocumentVersion, Document)
                    .join(Document, Document.id == DocumentVersion.document_id)
                    .where(
                        DocumentVersion.document_id == document_id,
                        DocumentVersion.version == int(version_text),
                    )
                )
            ).first()
            if row is None:
                continue
            version_row, document = row
            if document.deleted or document.state not in {"approved", "indexed"}:
                continue
            passage_hash = sha256_text(chunk.content)
            existing = pool.by_hash.get(passage_hash)
            if existing is not None:
                if existing.id not in seen_keys:
                    candidates.append(existing)
                    seen_keys.add(existing.id)
                continue
            passage = (
                await self.session.execute(
                    select(Passage).where(
                        Passage.document_version_id == version_row.id,
                        Passage.content_hash == passage_hash,
                    )
                )
            ).scalar_one_or_none()
            if passage is None:
                passage = Passage(
                    id=new_id("psg"),
                    document_version_id=version_row.id,
                    content_hash=passage_hash,
                    text=chunk.content,
                    locator=f"chunk {chunk.order}" if chunk.order is not None else None,
                    created_at=utcnow(),
                )
                self.session.add(passage)
                await self.session.flush()
            evidence_id = f"E{pool.next_index}"
            pool.next_index += 1
            basis_data = document.source_quality_basis or {"source": "default_unknown"}
            evidence = Evidence(
                id=evidence_id,
                evidence_id=passage.id,
                passage=chunk.content,
                passage_language=document.language,
                passage_translation=None,
                passage_hash=passage_hash,
                evidence_tier=1,
                relevance=max(0.0, min(1.0, chunk.score if chunk.score is not None else 0.5)),
                independence_key=_independence_key(document),
                provenance=Provenance(
                    document_id=document.id,
                    document_version=version_row.version,
                    title=document.title,
                    publisher=document.publisher,
                    authors=list(document.authors or []),
                    publication_date=document.publication_date,
                    url=document.url,
                    doi=document.doi,
                    locator=passage.locator,
                    dataset_id=document.dataset_id,
                    source_quality=document.source_quality,
                    source_quality_basis=SourceQualityBasis(**basis_data),
                    domain_tags=list(document.domain_tags or []),
                    language=document.language,
                    license=document.license,
                    redistribution=document.redistribution,
                    curator_organization=self.instance.organization,
                    origin_instance_id=document.origin_instance_id,
                    origin_document_id=document.origin_document_id,
                    approved_at=document.approved_at,
                    indexed_at=document.updated_at,
                ),
            )
            pool.by_hash[passage_hash] = evidence
            pool.by_id[evidence_id] = evidence
            candidates.append(evidence)
            seen_keys.add(evidence_id)
        return candidates

    async def _upsert_gap(
        self, *, query: str, language: str, topics: list[str], result_id: str
    ) -> None:
        normalized = _normalize_topic(query)
        existing = (
            await self.session.execute(
                select(CorpusGap).where(CorpusGap.normalized_topic == normalized)
            )
        ).scalar_one_or_none()
        now = utcnow()
        if existing is None:
            self.session.add(
                CorpusGap(
                    id=new_id("gap"),
                    normalized_topic=normalized,
                    query=query[:2000],
                    language=language,
                    topics=topics,
                    frequency=1,
                    sample_result_ids=[result_id],
                    state="open",
                    first_seen=now,
                    last_seen=now,
                )
            )
        else:
            existing.frequency += 1
            existing.last_seen = now
            samples = list(existing.sample_result_ids or [])
            if result_id not in samples:
                samples.append(result_id)
            existing.sample_result_ids = samples[-20:]

    def _pipeline_info(self) -> PipelineInfo:
        return PipelineInfo(
            software_version="0.1.0",
            pipeline_version=PIPELINE_VERSION,
            corpus_version=self.instance.corpus_version,
            config_hash=config_hash(self.settings, self.publishers, self.methodology),
            publisher_list_version=self.publishers.version,
            embedding_model_id=None,
            models={
                "extract": FS_EXTRACT,
                "verify": FS_VERIFY,
                "audit": FS_AUDIT,
                "moderation": FS_MODERATION,
            },
            prompt_versions={"extract": "1", "verify": "1", "moderation": "1"},
        )


_FILE_SOURCE_RE = re.compile(r"(doc_[A-Za-z0-9]+)@v(\d+)")


def _retrieval_query(
    statement: str, extraction: ExtractionResult, local_keywords: list[str]
) -> str:
    keywords = _dedupe([*extraction.keywords_low, *local_keywords])
    if keywords:
        return f"{statement} {' '.join(keywords[:8])}"
    return statement


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        cleaned = value.strip()
        if cleaned and cleaned.casefold() not in {item.casefold() for item in result}:
            result.append(cleaned)
    return result


def _independence_key(document: Document) -> str:
    if document.doi:
        return f"doi:{_normalize_doi(document.doi)}"
    if document.url:
        parsed = urlparse(document.url)
        host = (parsed.hostname or "").lower()
        path = parsed.path.rstrip("/")
        return f"url:{host}{path}"
    published = document.publication_date.isoformat() if document.publication_date else "undated"
    return f"pub:{document.publisher.casefold()}|{document.title.casefold()}|{published}"


def _normalize_doi(value: str) -> str:
    lowered = value.casefold().strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if lowered.startswith(prefix):
            return lowered[len(prefix) :]
    return lowered


def _normalize_topic(value: str) -> str:
    lowered = re.sub(r"\s+", " ", value.casefold()).strip()
    lowered = re.sub(r"[^\w\s]", "", lowered)
    return lowered[:300] or "empty"


def _evidence_refs(ids: list[str], pool: dict[str, Evidence]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for evidence_id in ids:
        item = pool.get(evidence_id)
        if item is None:
            continue
        refs.append(
            {
                "evidence_id": item.evidence_id,
                "document_id": item.provenance.document_id,
                "locator": item.provenance.locator,
            }
        )
    return refs


def _cited_evidence_ids(statements: list[Statement]) -> list[str]:
    seen: list[str] = []
    for statement in statements:
        for link in statement.evidence_links:
            if link.evidence_id not in seen:
                seen.append(link.evidence_id)
        for evidence_items in (statement.what_is_true, statement.what_is_missing):
            for evidence_item in evidence_items:
                for evidence_id in evidence_item.evidence:
                    if evidence_id not in seen:
                        seen.append(evidence_id)
    return seen


def _dedupe_warnings(warnings: list[WarningInfo]) -> list[WarningInfo]:
    seen: set[tuple[str, str, str | None]] = set()
    result: list[WarningInfo] = []
    for warning in warnings:
        key = (warning.code, warning.message, warning.statement_id)
        if key not in seen:
            seen.add(key)
            result.append(warning)
    return result


def _dedupe_issues(issues: list[ArgumentIssue]) -> list[ArgumentIssue]:
    seen: set[tuple[str, str]] = set()
    result: list[ArgumentIssue] = []
    for issue in issues:
        key = (issue.pattern, issue.explanation)
        if key not in seen:
            seen.add(key)
            result.append(issue)
        else:
            existing = next(item for item in result if (item.pattern, item.explanation) == key)
            for statement_id in issue.statement_ids:
                if statement_id not in existing.statement_ids:
                    existing.statement_ids.append(statement_id)
    return result


def config_hash(settings: Settings, publishers: PublisherRegistry, methodology: Methodology) -> str:
    payload = {
        "pipeline": PIPELINE_VERSION,
        "aliases": [FS_EXTRACT, FS_VERIFY, FS_AUDIT, FS_MODERATION],
        "publishers": publishers.version,
        "patterns": methodology.patterns_version,
        "topics": sorted(methodology.checklists),
        "languages": sorted(settings.supported_languages),
    }
    return "sha256:" + hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


# A typed helper used by the refusal path so the API and the worker share one shape.
def refused_result(
    *,
    result_id: str,
    job_id: str,
    text: str,
    language: str,
    moderation: ModerationInfo,
    pipeline: PipelineInfo,
    user_id: str | None = None,
) -> FactCheckResult:
    now = utcnow()
    return FactCheckResult(
        id=result_id,
        job_id=job_id,
        version=1,
        status="refused",
        preliminary=False,
        turn_type=TurnType.NEW_CLAIM,
        input=InputInfo(type="text", text=normalize_text(text), language=language),
        detected_language=language,
        response_language=language,
        overall_verdict=None,
        overall_explanation=refusal_text(language),
        statements=[],
        evidence=[],
        moderation=moderation,
        warnings=[WarningInfo(code="moderation_flagged", message="The input was blocked.")],
        pipeline=pipeline,
        created_at=now,
        completed_at=now,
    )
