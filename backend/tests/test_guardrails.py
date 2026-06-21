"""Grounding gate + PII redaction guardrails."""

from __future__ import annotations

import pytest

from src.agent.guardrails import confidence, is_grounded, redact_pii, refusal_message


def test_confidence_is_a_monotonic_sigmoid() -> None:
    assert confidence(5.0) > confidence(0.0) > confidence(-5.0)
    assert confidence(0.0) == pytest.approx(0.5)
    assert 0.0 < confidence(-5.0) < confidence(5.0) < 1.0


def test_is_grounded_threshold() -> None:
    assert is_grounded(5.0, 0.5) is True       # confident
    assert is_grounded(-5.0, 0.5) is False      # not confident -> refuse
    assert is_grounded(0.0, 0.5) is True        # sigmoid(0)=0.5 meets 0.5
    assert is_grounded(1.0, 0.0) is True         # gate off (0.0)


def test_refusal_message_is_safe() -> None:
    assert "follow up" in refusal_message().lower()


def test_redacts_email_and_phone() -> None:
    out = redact_pii("Reach me at jane.doe@example.com or +216 12 345 678 tomorrow.")
    assert "[redacted-email]" in out
    assert "[redacted-phone]" in out
    assert "@" not in out


def test_keeps_salary_figures_and_names() -> None:
    out = redact_pii("Amina expects 65,000 to 85,000 euros and 3 weeks notice.")
    assert "Amina" in out                 # names are kept (needed for screening)
    assert "65,000" in out and "85,000" in out
    assert "redacted" not in out


def test_empty_text_is_unchanged() -> None:
    assert redact_pii("") == ""
