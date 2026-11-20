"""The relevance cut over LightRAG candidates (DECISIONS.md D68).

Stock LightRAG returned 13 of 18 documents for an off-corpus query and 15 of 18 for
"Köln Familien" because its 0.2 floor lies below every passage. These tests pin the pure
rule that replaces "everything above 0.2" with "above the floor and near the best match".
"""

from __future__ import annotations

import math

import pytest
from app.retrieval.relevance import RelevancePolicy, cosine, relevance_cut

POLICY = RelevancePolicy(floor=0.40, margin=0.15)


def test_an_off_corpus_query_keeps_nothing_when_every_score_is_below_the_floor() -> None:
    """Measured: an off-corpus budget claim peaked at 0.333 against the dpa corpus."""
    assert relevance_cut([0.333, 0.320, 0.301, 0.240], POLICY) == [False] * 4


def test_a_clear_match_drops_the_flat_tail_of_unrelated_documents() -> None:
    """Measured: "Köln Familien" scored 0.540 for Cologne and at most 0.370 elsewhere."""
    assert relevance_cut([0.540, 0.370, 0.364, 0.348], POLICY) == [True, False, False, False]


def test_documents_near_the_best_match_are_all_kept() -> None:
    """A contradiction pair scores alike; both must survive for `contested` to be possible."""
    assert relevance_cut([0.885, 0.813, 0.730, 0.584], POLICY) == [True, True, False, False]


def test_the_floor_wins_over_the_margin_for_a_weak_best_match() -> None:
    assert relevance_cut([0.45, 0.41, 0.39], POLICY) == [True, True, False]


def test_a_score_exactly_at_the_threshold_is_kept() -> None:
    assert relevance_cut([0.60, 0.45], POLICY) == [True, True]
    assert relevance_cut([0.40], POLICY) == [True]


def test_an_empty_candidate_list_keeps_nothing() -> None:
    assert relevance_cut([], POLICY) == []


def test_cosine_is_the_normalised_dot_product() -> None:
    assert cosine([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine([1.0, 0.0], [0.0, 2.0]) == pytest.approx(0.0)
    assert cosine([1.0, 1.0], [1.0, 0.0]) == pytest.approx(1 / math.sqrt(2))
    assert cosine([0.0, 0.0], [1.0, 0.0]) == 0.0
