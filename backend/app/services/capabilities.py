"""One rule source for role requirements and model suitability (PROTOCOL §12.3).

The backend rejects an assignment with this rule and the future UI filters its choices
with the same function, so the two cannot drift (PURPOSE "Selection UI rules"). A
capability counts only when a probe recorded ``tested``; declared-but-untested
capabilities are ``assumed`` and do not satisfy a mandatory role.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.llm.aliases import (
    FS_AUDIT,
    FS_CHAT,
    FS_EMBEDDING,
    FS_EXTRACT,
    FS_MODERATION,
    FS_VERIFY,
    FS_VISION,
)

CAPABILITIES: tuple[str, ...] = (
    "chat",
    "structured_output",
    "vision",
    "embedding",
    "rerank",
    "moderation",
)


@dataclass(frozen=True)
class RoleRequirement:
    capabilities: tuple[str, ...]
    min_context: int | None = None
    multilingual: bool = False
    embedding_dim: int | None = None
    required: bool = True


ROLE_REQUIREMENTS: dict[str, RoleRequirement] = {
    FS_CHAT: RoleRequirement(("chat",)),
    FS_EXTRACT: RoleRequirement(("chat", "structured_output"), min_context=8_192),
    # Verification and audit read long passages and must tell German from English.
    FS_VERIFY: RoleRequirement(("chat", "structured_output"), min_context=8_192, multilingual=True),
    FS_AUDIT: RoleRequirement(("chat", "structured_output"), min_context=8_192, multilingual=True),
    FS_MODERATION: RoleRequirement(("chat", "structured_output")),
    FS_EMBEDDING: RoleRequirement(("embedding",), multilingual=True, embedding_dim=1024),
    FS_VISION: RoleRequirement(("chat", "vision", "structured_output")),
}

ROLE_LABELS: dict[str, str] = {
    FS_CHAT: "rendering",
    FS_EXTRACT: "extraction and LightRAG extraction",
    FS_VERIFY: "verification",
    FS_AUDIT: "audit",
    FS_MODERATION: "moderation",
    FS_EMBEDDING: "corpus embeddings",
    FS_VISION: "image input and figure descriptions",
}


@dataclass(frozen=True)
class ModelView:
    """The fields the rule needs; deliberately independent of the ORM row."""

    capabilities: frozenset[str] = field(default_factory=frozenset)
    tested: frozenset[str] = field(default_factory=frozenset)
    context_window: int | None = None
    embedding_dim: int | None = None
    multilingual: bool = False


def assignment_reasons(alias: str, model: ModelView) -> list[str]:
    """Return every reason the assignment would be rejected; empty means suitable."""
    requirement = ROLE_REQUIREMENTS.get(alias)
    if requirement is None:
        return [f"unknown_role:{alias}"]
    reasons: list[str] = []
    for capability in requirement.capabilities:
        if capability not in model.capabilities:
            reasons.append(f"missing_capability:{capability}")
        elif capability not in model.tested:
            reasons.append(f"capability_not_tested:{capability}")
    if requirement.min_context is not None and (
        model.context_window is None or model.context_window < requirement.min_context
    ):
        reasons.append(f"context_too_small:{requirement.min_context}")
    if requirement.multilingual and not model.multilingual:
        reasons.append("not_multilingual")
    if requirement.embedding_dim is not None and model.embedding_dim != requirement.embedding_dim:
        reasons.append(f"embedding_dim_mismatch:{requirement.embedding_dim}")
    return reasons


def is_suitable(alias: str, model: ModelView) -> bool:
    return not assignment_reasons(alias, model)
