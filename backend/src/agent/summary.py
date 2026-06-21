"""Grounded post-call summary.

A short, factual recruiter-facing summary of the screening call, grounded in the
transcript — no invention, no recommendation the candidate didn't support.
"""

from __future__ import annotations

import logging

from src.agent.state import ConversationState
from src.providers.llm.base import LLMProvider
from src.providers.types import Message, Role

log = logging.getLogger("echoassist.agent.summary")

_SYSTEM = (
    "You write a concise post-call summary of a candidate phone screening for a "
    "recruiter. Use ONLY what was said in the transcript — do not invent facts. Write "
    "3 to 4 plain sentences covering experience, tech stack, availability, remote/location, "
    "salary expectation, and your overall impression. No bullet points, no markdown."
)

_FALLBACK = "No summary available: the call has no transcript."


class SummaryGenerator:
    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def summarize(self, state: ConversationState) -> str:
        if not state.transcript:
            return _FALLBACK
        transcript = "\n".join(f"{t['role']}: {t['text']}" for t in state.transcript)
        response = await self._llm.chat(
            [Message(Role.SYSTEM, _SYSTEM), Message(Role.USER, transcript)]
        )
        return response.text.strip() or _FALLBACK
