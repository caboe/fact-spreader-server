"""Wire enums shared by the API, the pipeline and the tests (PROTOCOL §2)."""

from __future__ import annotations

from enum import StrEnum


class Verdict(StrEnum):
    TRUE = "true"
    TRUE_BUT_MISLEADING = "true_but_misleading"
    PARTIALLY_FALSE = "partially_false"
    FALSE = "false"
    CONTESTED = "contested"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    NOT_CHECKABLE = "not_checkable"


TRUTH_BEARING = {
    Verdict.TRUE,
    Verdict.TRUE_BUT_MISLEADING,
    Verdict.PARTIALLY_FALSE,
    Verdict.FALSE,
    Verdict.CONTESTED,
}


class Stance(StrEnum):
    SUPPORTS = "supports"
    REFUTES = "refutes"
    CONTEXT = "context"
    MIXED = "mixed"


class StatementKind(StrEnum):
    FACT = "fact"
    OPINION = "opinion"
    RHETORIC = "rhetoric"
    IMPLIED_CONCLUSION = "implied_conclusion"
    NORMATIVE = "normative"


class ResultStatus(StrEnum):
    COMPLETE = "complete"
    NEEDS_CLARIFICATION = "needs_clarification"
    REFUSED = "refused"
    ERROR = "error"


class JobState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class OutputFormat(StrEnum):
    SUBSTANCE = "substance"
    PERSONA = "persona"
    COMPACT = "compact"


class TurnType(StrEnum):
    NEW_CLAIM = "new_claim"
    REPEATED_CLAIM = "repeated_claim"
    FOLLOW_UP_CLAIM = "follow_up_claim"
    EVIDENCE_CHALLENGE = "evidence_challenge"
    CLARIFICATION_ANSWER = "clarification_answer"
    QUESTION = "question"
    META = "meta"
    OFF_TOPIC = "off_topic"
    ABUSIVE = "abusive"


class ModerationAction(StrEnum):
    ALLOW = "allow"
    FLAG_ONLY = "flag_only"
    ROUTE_ABUSIVE = "route_abusive"
    BLOCK = "block"


PERMISSIONS: tuple[str, ...] = (
    "chat:use",
    "claims:submit",
    "claims:recheck",
    "search:use",
    "documents:submit",
    "documents:review",
    "quality:read",
    "config:manage",
    "methodology:manage",
    "users:manage",
    "usage:read",
    "devices:manage",
)


def is_truth_bearing(value: Verdict | str | None) -> bool:
    return value in TRUTH_BEARING


ROLE_TEMPLATES: dict[str, tuple[str, ...]] = {
    "admin": PERMISSIONS,
    "editor": (
        "chat:use",
        "claims:submit",
        "claims:recheck",
        "search:use",
        "documents:submit",
        "documents:review",
        "quality:read",
        "devices:manage",
        "usage:read",
    ),
    "researcher": (
        "chat:use",
        "claims:submit",
        "search:use",
        "devices:manage",
        "usage:read",
    ),
    "user": (
        "chat:use",
        "claims:submit",
        "search:use",
        "devices:manage",
    ),
}
