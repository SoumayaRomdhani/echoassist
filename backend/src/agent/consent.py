"""Consent classification for the call-start consent gate.

Sprint 1 uses a keyword/phrase heuristic (FR + EN) — enough to gate the
interview on an explicit yes/no. The contract is just ``text -> ConsentDecision``,
so a more robust classifier (e.g. LLM-based) can replace it at Sprint 3 without
touching callers.
"""

from __future__ import annotations

import hashlib
import re
from enum import StrEnum


class ConsentDecision(StrEnum):
    ACCEPTED = "accepted"
    REFUSED = "refused"
    AMBIGUOUS = "ambiguous"


# Phrases are checked before single words because they override an embedded
# affirmation/negation (e.g. "no problem" is acceptance despite the word "no").
_AMBIGUOUS_PHRASES = (
    "not sure", "unsure", "dont know", "no idea", "maybe", "perhaps",
    "pas sur", "je ne sais pas", "sais pas", "peut etre", "peut-etre",
)
_ACCEPT_PHRASES = (
    "no problem", "no worries", "dont mind", "do not mind", "go ahead",
    "pas de probleme", "pas de souci", "pas de soucis", "ca marche",
    "allez-y", "allez y", "vas-y", "vas y",
)
# Includes negated affirmations ("do not consent", "dont continue") so a negated
# accept-word is treated as refusal rather than acceptance.
_REFUSE_PHRASES = (
    "dont consent", "do not consent", "dont agree", "do not agree", "i refuse",
    "dont continue", "do not continue", "dont proceed", "do not proceed",
    "dont go ahead", "do not go ahead", "no thank", "rather not", "hang up",
    "je refuse", "je ne consens pas", "raccroch", "arret",
)

_ACCEPT_WORDS = frozenset({
    "yes", "yeah", "yep", "yup", "sure", "ok", "okay", "okey", "agree", "agreed",
    "consent", "continue", "proceed", "fine", "alright",
    "oui", "ouais", "daccord", "accord", "jaccepte", "accepte", "consens", "continuez",
})
_REFUSE_WORDS = frozenset({
    "no", "nope", "nah", "dont", "stop", "refuse", "never",
    "non", "jamais", "arretez", "raccrochez",
})

_ACCENTS = str.maketrans("àâäéèêëîïôöùûüç", "aaaeeeeiioouuuc")


def _normalize(text: str) -> str:
    """Lowercase, drop apostrophes/accents, keep letters/digits/spaces/hyphens."""
    lowered = text.lower().replace("'", "").replace("’", "").translate(_ACCENTS)
    return re.sub(r"[^a-z0-9\s-]", " ", lowered).strip()


def _tokens(text: str) -> set[str]:
    return {token for token in re.split(r"[\s-]+", text) if token}


def _strip(text: str, phrases: tuple[str, ...]) -> str:
    for phrase in phrases:
        text = text.replace(phrase, " ")
    return text


def classify_consent(text: str) -> ConsentDecision:
    """Classify a caller's spoken response to the consent question."""
    if not text or not text.strip():
        return ConsentDecision.AMBIGUOUS

    norm = _normalize(text)
    if any(phrase in norm for phrase in _AMBIGUOUS_PHRASES):
        return ConsentDecision.AMBIGUOUS

    # Evaluate each side on the text with the *other* side's phrases removed, so a
    # negated accept-word ("do not consent") counts only as refusal, and an
    # accept-phrase containing a negation ("no problem") counts only as acceptance.
    accept = any(phrase in norm for phrase in _ACCEPT_PHRASES) or bool(
        _tokens(_strip(norm, _REFUSE_PHRASES)) & _ACCEPT_WORDS
    )
    refuse = any(phrase in norm for phrase in _REFUSE_PHRASES) or bool(
        _tokens(_strip(norm, _ACCEPT_PHRASES)) & _REFUSE_WORDS
    )

    if accept and not refuse:
        return ConsentDecision.ACCEPTED
    if refuse and not accept:
        return ConsentDecision.REFUSED
    return ConsentDecision.AMBIGUOUS


def disclosure_hash(disclosure: str) -> str:
    """Stable sha256 of the exact disclosure spoken — proves which AI notice was given.

    Persisted on the consent audit record so the compliance trail captures *which*
    AI disclosure the caller heard (ARCHITECTURE.md §10), independent of any later
    wording change. Shared by every call entry point (API runner + live transport)
    so the recorded hash is identical however the call was placed.
    """
    return hashlib.sha256(disclosure.strip().encode("utf-8")).hexdigest()
