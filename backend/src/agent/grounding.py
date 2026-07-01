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

from src.agent.guardrails import is_grounded, refusal_message
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


# Public alias for reuse (e.g. cleaning streamed sentences before TTS).
strip_citations = _spoken


# Brevity rule shared by both answering paths — fewer tokens to generate and to
# speak means a lower TTFA and a shorter turn (AMELIORATIONS.md, Axe 1).
_BREVITY = (
    "Answer in one or two short sentences: lead with the answer, with no preamble and "
    "without restating the question — it will be spoken aloud."
)

_GROUNDING_RULES = (
    "Answer using ONLY the knowledge base. To find information, call the "
    "search_knowledge_base tool with a focused query. Base your answer strictly on the "
    "returned passages — do not use outside knowledge. Cite every fact with its source "
    "filename in square brackets exactly as shown, e.g. [interview_process.md]. If the "
    "passages do not contain the answer, say you don't have that information and will "
    f"have a recruiter follow up. {_BREVITY}"
)

# Retrieve-then-read path (L3): we have already retrieved, so the passages are given
# inline and the model just reads them — no tool, one LLM call instead of two.
_READ_RULES = (
    "Answer the caller's question using ONLY the knowledge-base passages below. Do not "
    "use any outside knowledge. Cite every fact with its source filename in square "
    "brackets exactly as shown, e.g. [interview_process.md]. If the passages do not "
    "contain the answer, say you don't have that information and a recruiter will "
    f"follow up. {_BREVITY}\n\n"
    "Knowledge base:\n{context}"
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
        retrieve_then_read: bool = False,
    ) -> None:
        self._llm = llm
        self._retriever = retriever
        self._base_prompt = system_prompt
        self._system_prompt = f"{system_prompt}\n\n{_GROUNDING_RULES}"
        self._max_tool_iters = max_tool_iters
        self._min_confidence = min_confidence  # grounding gate (0.0 = off)
        # retrieve_then_read: skip the model's "decide to search" tool round-trip and
        # retrieve directly (−1 LLM call/turn, L3). Defaults off so the constructor
        # keeps the Sprint-2 tool-loop semantics; the app enables it via settings.
        self._retrieve_then_read = retrieve_then_read

    @staticmethod
    def _format_context(chunks: list[ScoredChunk]) -> str:
        if not chunks:
            return "No relevant documents were found."
        return "\n\n".join(f"[{c.chunk.source}] {c.chunk.text}" for c in chunks)

    @staticmethod
    def _citations(text: str, retrieved: list[ScoredChunk]) -> list[str]:
        sources = {c.chunk.source for c in retrieved}
        return sorted(s for s in sources if f"[{s}]" in text)

    async def _retrieve_confident(
        self, query: str, *, label: str = "retrieve"
    ) -> list[ScoredChunk]:
        """Retrieve, then keep only chunks the reranker is confident about.

        The grounding gate drops low-confidence chunks so the agent answers from the
        knowledge base or refuses — never from weak/irrelevant context.
        """
        chunks = await asyncio.to_thread(self._retriever.retrieve, query)
        confident = [c for c in chunks if is_grounded(c.score, self._min_confidence)]
        log.info(
            "%s query=%r -> %d chunks (%d confident)", label, query, len(chunks), len(confident)
        )
        return confident

    def _read_messages(self, question: str, chunks: list[ScoredChunk]) -> list[Message]:
        """Build the single-shot read prompt with the retrieved passages inlined."""
        rules = _READ_RULES.format(context=self._format_context(chunks))
        system = Message(Role.SYSTEM, f"{self._base_prompt}\n\n{rules}")
        return [system, Message(Role.USER, question)]

    async def answer(self, question: str) -> GroundedAnswer:
        if self._retrieve_then_read:
            return await self._answer_direct(question)
        return await self._answer_with_tools(question)

    async def _answer_direct(self, question: str) -> GroundedAnswer:
        """Retrieve-then-read (L3): retrieve once, then one grounded LLM read."""
        confident = await self._retrieve_confident(question)
        if not confident:  # deterministic refusal — never read empty/weak context
            return GroundedAnswer(text=refusal_message(), citations=[], tool_calls=0)
        response = await self._llm.chat(self._read_messages(question, confident))
        return self._finalize(response.text, confident, tool_calls=0)

    async def _answer_with_tools(self, question: str) -> GroundedAnswer:
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
                confident = await self._retrieve_confident(query, label="tool search")
                retrieved.extend(confident)
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

    async def answer_streaming(self, question: str):
        """Stream the grounded answer as raw text deltas (with ``[source]`` markers).

        Same retrieval + deterministic-refusal logic as :meth:`answer`, but the
        FINAL answer is produced with ``chat_stream`` so audio can start before the
        whole answer is written. Citation stripping happens downstream, per sentence.
        """
        if self._retrieve_then_read:
            confident = await self._retrieve_confident(question)
            if not confident:  # deterministic refusal — never stream ungrounded
                yield refusal_message()
                return
            async for delta in self._llm.chat_stream(self._read_messages(question, confident)):
                yield delta
            return

        messages = [Message(Role.SYSTEM, self._system_prompt), Message(Role.USER, question)]
        retrieved: list[ScoredChunk] = []

        for _ in range(self._max_tool_iters):
            response = await self._llm.chat(messages, tools=[SEARCH_TOOL])
            if not response.tool_calls:
                break  # the model is ready to answer
            messages.append(Message(Role.ASSISTANT, response.text, tool_calls=response.tool_calls))
            for call in response.tool_calls:
                query = str(call.arguments.get("query") or question)
                confident = await self._retrieve_confident(query, label="tool search")
                retrieved.extend(confident)
                messages.append(
                    Message(Role.TOOL, self._format_context(confident),
                            tool_call_id=call.id, name=call.name)
                )

        if not retrieved:  # deterministic refusal — never stream an ungrounded answer
            yield refusal_message()
            return
        async for delta in self._llm.chat_stream(messages):
            yield delta

    def _finalize(
        self, raw_text: str, retrieved: list[ScoredChunk], tool_calls: int
    ) -> GroundedAnswer:
        # Deterministic grounding: with no confident chunk, refuse — never trust the
        # LLM to have refused on its own (guarantees "no answer outside the KB").
        if not retrieved:
            return GroundedAnswer(text=refusal_message(), citations=[], tool_calls=tool_calls)
        # Citations are parsed from the raw model text; the spoken text has them stripped.
        return GroundedAnswer(
            text=_spoken(raw_text),
            citations=self._citations(raw_text, retrieved),
            retrieved=retrieved,
            tool_calls=tool_calls,
        )
