"""Unit tests for the FR/EN consent classifier."""

from __future__ import annotations

import pytest

from src.agent.consent import ConsentDecision, classify_consent, disclosure_hash


@pytest.mark.parametrize(
    "text",
    [
        "Yes, that's fine, you can continue.",
        "Yeah sure, go ahead.",
        "OK.",
        "No problem.",            # embedded "no" but means acceptance
        "I consent.",
        "Oui, d'accord.",
        "Ouais, allez-y.",
        "Pas de problème, continuez.",
    ],
)
def test_accepted(text: str) -> None:
    assert classify_consent(text) is ConsentDecision.ACCEPTED


@pytest.mark.parametrize(
    "text",
    [
        "No, I'd rather not.",
        "No.",
        "Please don't continue.",
        "I refuse.",
        "I do not consent.",
        "Non, je refuse.",
        "Non merci.",
        "Arrêtez s'il vous plaît.",
    ],
)
def test_refused(text: str) -> None:
    assert classify_consent(text) is ConsentDecision.REFUSED


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "Hmm, I'm not sure.",
        "Maybe?",
        "Who is this?",
        "Yes but actually no.",   # conflicting signals
        "Je ne sais pas.",
    ],
)
def test_ambiguous(text: str) -> None:
    assert classify_consent(text) is ConsentDecision.AMBIGUOUS


def test_disclosure_hash_is_stable_and_whitespace_insensitive() -> None:
    base = disclosure_hash("This call may be recorded.")
    assert base == disclosure_hash("  This call may be recorded.  ")  # trims surrounding space
    assert base != disclosure_hash("A different notice.")
    assert len(base) == 64 and all(c in "0123456789abcdef" for c in base)  # sha256 hex
