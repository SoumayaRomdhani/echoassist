"""Reciprocal Rank Fusion."""

from __future__ import annotations

from src.rag.retriever import reciprocal_rank_fusion


def test_items_ranked_high_in_both_lists_win() -> None:
    dense = ["a", "b", "c"]
    sparse = ["b", "a", "d"]
    scores = reciprocal_rank_fusion([dense, sparse], k=60)
    ranked = sorted(scores, key=scores.get, reverse=True)
    # "a" (1st, 2nd) and "b" (2nd, 1st) appear in both -> ahead of single-list items.
    assert set(ranked[:2]) == {"a", "b"}
    assert ranked[-1] in {"c", "d"}


def test_first_rank_scores_more_than_lower_rank() -> None:
    scores = reciprocal_rank_fusion([["x", "y"]], k=60)
    assert scores["x"] > scores["y"]


def test_k_constant_dampens_rank_gaps() -> None:
    small_k = reciprocal_rank_fusion([["x", "y"]], k=1)
    large_k = reciprocal_rank_fusion([["x", "y"]], k=1000)
    # A larger k flattens the gap between consecutive ranks.
    assert (small_k["x"] - small_k["y"]) > (large_k["x"] - large_k["y"])


def test_empty_input_is_empty() -> None:
    assert reciprocal_rank_fusion([]) == {}
    assert reciprocal_rank_fusion([[]]) == {}
