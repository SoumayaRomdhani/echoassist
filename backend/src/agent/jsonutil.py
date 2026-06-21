"""Tolerant JSON extraction from LLM text output.

Models sometimes wrap JSON in prose or code fences; this pulls the first
balanced object out and parses it, returning ``None`` on failure.
"""

from __future__ import annotations

import json


def extract_json(text: str) -> dict | None:
    if not text:
        return None
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None
