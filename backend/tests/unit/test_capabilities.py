"""Role requirements are one rule for the backend and the future UI (PROTOCOL §12.3)."""

from __future__ import annotations

from app.llm.aliases import FS_AUDIT, FS_EMBEDDING, FS_EXTRACT, FS_VISION
from app.services.capabilities import (
    ROLE_REQUIREMENTS,
    ModelView,
    assignment_reasons,
    is_suitable,
)


def test_a_missing_capability_is_named_in_the_reason() -> None:
    view = ModelView(capabilities=frozenset({"chat"}))
    assert "missing_capability:structured_output" in assignment_reasons(FS_EXTRACT, view)


def test_a_declared_but_untested_capability_does_not_satisfy_a_role() -> None:
    view = ModelView(capabilities=frozenset({"chat"}), tested=frozenset({"chat"}))
    assert assignment_reasons(FS_VISION, view) == [
        "missing_capability:vision",
        "missing_capability:structured_output",
    ]
    structured = ModelView(
        capabilities=frozenset({"chat", "structured_output", "vision"}),
        tested=frozenset({"chat", "structured_output"}),
    )
    assert assignment_reasons(FS_VISION, structured) == ["capability_not_tested:vision"]


def test_context_multilingual_and_dimension_are_checked_for_mandatory_roles() -> None:
    small = ModelView(
        capabilities=frozenset({"chat", "structured_output"}),
        tested=frozenset({"chat", "structured_output"}),
        context_window=4096,
    )
    assert "context_too_small:8192" in assignment_reasons(FS_AUDIT, small)
    monolingual = ModelView(
        capabilities=frozenset({"chat", "structured_output"}),
        tested=frozenset({"chat", "structured_output"}),
        context_window=16000,
    )
    assert "not_multilingual" in assignment_reasons(FS_AUDIT, monolingual)
    right_size = ModelView(
        capabilities=frozenset({"embedding"}),
        tested=frozenset({"embedding"}),
        embedding_dim=1024,
        multilingual=True,
    )
    assert assignment_reasons(FS_EMBEDDING, right_size) == []
    assert assignment_reasons(
        FS_EMBEDDING,
        ModelView(
            capabilities=frozenset({"embedding"}),
            tested=frozenset({"embedding"}),
            embedding_dim=768,
            multilingual=True,
        ),
    ) == ["embedding_dim_mismatch:1024"]


def test_a_tested_suitable_model_has_no_reasons_and_every_role_is_known() -> None:
    view = ModelView(
        capabilities=frozenset({"chat", "structured_output"}),
        tested=frozenset({"chat", "structured_output"}),
        context_window=16000,
        multilingual=True,
    )
    assert is_suitable(FS_EXTRACT, view)
    assert assignment_reasons("fs-unknown", view) == ["unknown_role:fs-unknown"]
    assert set(ROLE_REQUIREMENTS) == {
        "fs-chat",
        "fs-extract",
        "fs-verify",
        "fs-audit",
        "fs-moderation",
        "fs-embedding",
        "fs-vision",
    }
