"""LightRAG document status: when indexing is really finished."""

from __future__ import annotations

import pytest
from app.retrieval.lightrag import _has_unfinished_documents


@pytest.mark.parametrize("state", ["pending", "parsing", "analyzing", "preprocessed", "processing"])
def test_every_state_before_a_final_one_counts_as_unfinished(state: str) -> None:
    """Prevents seed-fixtures from reporting ready while documents are still parsed.

    LightRAG v1.5.0 added PARSING and ANALYZING; only pending/processing were checked, so
    the wait returned with 21 of 23 fixture documents still in flight.
    """
    assert _has_unfinished_documents({"statuses": {state: [{"id": "doc-1"}]}})
    assert _has_unfinished_documents({"statuses": {state: 1}})


def test_only_processed_and_failed_documents_mean_idle() -> None:
    assert not _has_unfinished_documents(
        {"statuses": {"processed": [{"id": "doc-1"}], "failed": [{"id": "doc-2"}]}}
    )
    assert not _has_unfinished_documents({"statuses": {"parsing": []}})
