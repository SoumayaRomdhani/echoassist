"""Quality & compliance guardrails (ARCHITECTURE.md §10).

- Grounding gate: keep only retrieved chunks the reranker is confident about, so
  the agent answers from the knowledge base or refuses — never from thin air.
- PII redaction: mask emails and phone numbers before persistence. Candidate
  names are kept (they are the point of a screening record).
"""

from __future__ import annotations

import math
import re

# --- Grounding ------------------------------------------------------------- #
_REFUSAL = (
    "I don't have that information in the knowledge base. I'll note it and have a "
    "recruiter follow up."
)


def confidence(rerank_score: float) -> float:
    """Map a cross-encoder rerank score (logit) to a 0..1 confidence."""
    return 1.0 / (1.0 + math.exp(-rerank_score))


def is_grounded(rerank_score: float, min_confidence: float) -> bool:
    """True if a retrieved chunk is confident enough to ground an answer."""
    return confidence(rerank_score) >= min_confidence


def refusal_message() -> str:
    return _REFUSAL


# --- PII redaction --------------------------------------------------------- #
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
# Phone-like runs of digits/separators; redacted only if they hold enough digits
# (so figures like salaries "65,000" are not mistaken for phone numbers).
_PHONE_RE = re.compile(r"\+?\d[\d\s().\-]{6,}\d")
_MIN_PHONE_DIGITS = 8


def _redact_phone(match: re.Match[str]) -> str:
    digits = sum(ch.isdigit() for ch in match.group())
    return "[redacted-phone]" if digits >= _MIN_PHONE_DIGITS else match.group()


def redact_pii(text: str) -> str:
    """Mask emails and phone numbers in free text."""
    if not text:
        return text
    text = _EMAIL_RE.sub("[redacted-email]", text)
    return _PHONE_RE.sub(_redact_phone, text)
