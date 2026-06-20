"""Grounded question answering via retrieval as an LLM tool (function calling).

The model is given a ``search_knowledge_base`` tool. It decides when to call it,
we run the hybrid retriever, feed the passages back, and the model produces an
answer cited to the source documents. This is the Sprint 2 DoD path; Sprint 3
wires it into the full interview dialogue.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

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
    ) -> None:
        self._llm = llm
        self._retriever = retriever
        self._system_prompt = f"{system_prompt}\n\n{_GROUNDING_RULES}"
        self._max_tool_iters = max_tool_iters

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
                return GroundedAnswer(
                    text=response.text,
                    citations=self._citations(response.text, retrieved),
                    retrieved=retrieved,
                    tool_calls=tool_calls,
                )

            messages.append(Message(Role.ASSISTANT, response.text, tool_calls=response.tool_calls))
            for call in response.tool_calls:
                tool_calls += 1
                query = str(call.arguments.get("query") or question)
                chunks = await asyncio.to_thread(self._retriever.retrieve, query)
                retrieved.extend(chunks)
                log.info("tool search query=%r -> %d chunks", query, len(chunks))
                messages.append(
                    Message(
                        Role.TOOL,
                        self._format_context(chunks),
                        tool_call_id=call.id,
                        name=call.name,
                    )
                )

        # Tool budget exhausted: ask once more without tools to force a final answer.
        final = await self._llm.chat(messages)
        return GroundedAnswer(
            text=final.text,
            citations=self._citations(final.text, retrieved),
            retrieved=retrieved,
            tool_calls=tool_calls,
        )
