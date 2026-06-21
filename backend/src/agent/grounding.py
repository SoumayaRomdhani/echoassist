"""Grounded question answering via retrieval as an LLM tool (function calling).

The model is given a ``search_knowledge_base`` tool. It decides when to call it,
we run the hybrid retriever, feed the passages back, and the model produces an
answer cited to the source documents. This is the Sprint 2 DoD path; Sprint 3
wires it into the full interview dialogue.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field

from src.agent.guardrails import is_grounded
from src.providers.llm.base import LLMProvider
from src.providers.types import Message, Role, ToolSpec
from src.rag.retriever import Retriever
from src.rag.types import ScoredChunk

log = logging.getLogger("echoassist.agent.grounding")

SEARCH_TOOL = ToolSpec(
    name="search_knowledge_base",
    description=(
        "Search the screening knowledge base for passages relevant to the caller's "
        "question. Call this before answering any factual question about the role, "
        "company, hiring process, benefits, or policies."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "A focused search query."}
        },
        "required": ["query"],
    },
)

_CITATION_PATTERN = re.compile(r"\s*\[[^\]]*\]")


def _spoken(text: str) -> str:
    """Strip bracketed source citations so the spoken answer is natural prose.

    The model still emits ``[source]`` (so we can capture the citation in metadata),
    but the caller hears a clean sentence — the filename belongs in the dashboard,
    not the audio.
    """
    stripped = _CITATION_PATTERN.sub("", text)
    stripped = re.sub(r"\s+([.,;:!?])", r"\1", stripped)
    return re.sub(r"\s{2,}", " ", stripped).strip()


_GROUNDING_RULES = (
    "Answer using ONLY the knowledge base. To find information, call the "
    "search_knowledge_base tool with a focused query. Base your answer strictly on the "
    "returned passages — do not use outside knowledge. Cite every fact with its source "
    "filename in square brackets exactly as shown, e.g. [interview_process.md]. If the "
    "passages do not contain the answer, say you don't have that information and will "
    "have a recruiter follow up. Keep the answer concise and natural, as if spoken."
)


@dataclass(slots=True)
class GroundedAnswer:
    text: str
    citations: list[str]                       # source filenames cited in the answer
    retrieved: list[ScoredChunk] = field(default_factory=list)
    tool_calls: int = 0


class GroundedResponder:
    def __init__(
        self,
        llm: LLMProvider,
        retriever: Retriever,
        *,
        system_prompt: str,
        max_tool_iters: int = 3,
        min_confidence: float = 0.0,
    ) -> None:
        self._llm = llm
        self._retriever = retriever
        self._system_prompt = f"{system_prompt}\n\n{_GROUNDING_RULES}"
        self._max_tool_iters = max_tool_iters
        self._min_confidence = min_confidence  # grounding gate (0.0 = off)

    @staticmethod
    def _format_context(chunks: list[ScoredChunk]) -> str:
        if not chunks:
            return "No relevant documents were found."
        return "\n\n".join(f"[{c.chunk.source}] {c.chunk.text}" for c in chunks)

    @staticmethod
    def _citations(text: str, retrieved: list[ScoredChunk]) -> list[str]:
        sources = {c.chunk.source for c in retrieved}
        return sorted(s for s in sources if f"[{s}]" in text)

    async def answer(self, question: str) -> GroundedAnswer:
        messages = [Message(Role.SYSTEM, self._system_prompt), Message(Role.USER, question)]
        retrieved: list[ScoredChunk] = []
        tool_calls = 0

        for _ in range(self._max_tool_iters):
            response = await self._llm.chat(messages, tools=[SEARCH_TOOL])
            if not response.tool_calls:
                return self._finalize(response.text, retrieved, tool_calls)

            messages.append(Message(Role.ASSISTANT, response.text, tool_calls=response.tool_calls))
            for call in response.tool_calls:
                tool_calls += 1
                query = str(call.arguments.get("query") or question)
                chunks = await asyncio.to_thread(self._retriever.retrieve, query)
                # Grounding gate: drop low-confidence chunks so the model answers
                # from the KB or refuses — never from weak/irrelevant context.
                confident = [c for c in chunks if is_grounded(c.score, self._min_confidence)]
                retrieved.extend(confident)
                log.info(
                    "tool search query=%r -> %d chunks (%d confident)",
                    query, len(chunks), len(confident),
                )
                messages.append(
                    Message(
                        Role.TOOL,
                        self._format_context(confident),
                        tool_call_id=call.id,
                        name=call.name,
                    )
                )

        # Tool budget exhausted: ask once more without tools to force a final answer.
        final = await self._llm.chat(messages)
        return self._finalize(final.text, retrieved, tool_calls)

    def _finalize(
        self, raw_text: str, retrieved: list[ScoredChunk], tool_calls: int
    ) -> GroundedAnswer:
        # Citations are parsed from the raw model text; the spoken text has them stripped.
        return GroundedAnswer(
            text=_spoken(raw_text),
            citations=self._citations(raw_text, retrieved),
            retrieved=retrieved,
            tool_calls=tool_calls,
        )
