"""Eval metric helpers: word error rate + percentile."""

from __future__ import annotations

import pytest

from src.eval.latency_eval import percentile
from src.eval.transcription_eval import word_error_rate


def test_wer_identical_is_zero() -> None:
    assert word_error_rate("the cat sat", "the cat sat") == 0.0


def test_wer_normalizes_case_and_punctuation() -> None:
    assert word_error_rate("Hello, world!", "hello world") == 0.0


def test_wer_counts_substitution_deletion_insertion() -> None:
    assert word_error_rate("the cat sat", "the dog sat") == pytest.approx(1 / 3)  # 1 sub
    assert word_error_rate("a b c d", "a c d") == pytest.approx(1 / 4)            # 1 deletion
    assert word_error_rate("a b c", "a b c d") == pytest.approx(1 / 3)            # 1 insertion


def test_wer_empty_reference() -> None:
    assert word_error_rate("", "") == 0.0
    assert word_error_rate("", "extra") == 1.0


def test_percentile_basic() -> None:
    values = [10, 20, 30, 40, 50]
    assert percentile(values, 0) == 10
    assert percentile(values, 50) == 30
    assert percentile(values, 100) == 50


def test_percentile_interpolates_and_handles_empty() -> None:
    assert percentile([10, 20], 50) == pytest.approx(15)
    assert percentile([], 95) == 0.0
