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
import time
from dataclasses import dataclass, field

from src.agent.guardrails import is_grounded, refusal_message
from src.observability import latency
from src.providers.errors import ProviderError
from src.providers.llm.base import LLMProvider
from src.providers.types import Message, Role, ToolSpec
from src.rag.retriever import Retriever
from src.rag.types import ScoredChunk

log = logging.getLogger("echoassist.agent.grounding")

SEARCH_TOOL = ToolSpec(
    name="search_knowledge_base",
    description=(
        "Search the domain knowledge base for passages relevant to the caller's "
        "question. Call this before answering any factual question, using only the "
        "returned passages."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "A focused search query."}
        },
        "required": ["query"],
    },
)

# A bracketed source citation, optionally preceded by the connector phrase that only exists
# to introduce it ("as mentioned in [x]", "according to [x]", "see [x]", "in [x]"). Matching
# the connector *together with* the citation means we remove "as mentioned in." cleanly while
# never touching a legitimate word that merely happens to sit before punctuation (e.g. the
# "in" in "Log in." survives, because there is no citation after it).
_CITATION_PATTERN = re.compile(
    r"[\s,;:]*(?:\b(?:"
    r"as\s+(?:described|outlined|mentioned|noted|shown|stated|detailed|per)\s+in"
    r"|as\s+(?:described|outlined|mentioned|noted|shown|stated)"
    r"|according\s+to|based\s+on|as\s+per|refer\s+to|referring\s+to|see"
    r"|(?:described|outlined|mentioned|noted|shown|listed|found|detailed)\s+in"
    r"|in|per"
    r")\s+)?"
    r"(?:(?:our|the)\s+)?"          # absorb a dangling possessive ("as per our [x]", "in the [x]")
    r"\[[^\]]*\]",
    re.I,
)


# Passive-aggressive "you weren't listening" phrases that must never reach the caller — on a
# call they can't recall what was said before, so these only sound like a frustrated machine.
_BANNED_SPOKEN = re.compile(
    r"\b(?:"
    r"as (?:i )?(?:mentioned|said|stated|noted|explained|told you)"
    r"(?:\s+(?:earlier|before|previously|already|again))?"
    r"|like i (?:said|mentioned|told you)|as previously (?:mentioned|stated|noted)"
    r"|as we (?:discussed|talked about)|as you (?:already )?know"
    r")\b[,]?\s*",
    re.I,
)


def _spoken(text: str) -> str:
    """Strip bracketed source citations so the spoken answer is natural prose.

    The model still emits ``[source]`` (so we can capture the citation in metadata),
    but the caller hears a clean sentence — the filename belongs in the dashboard, not
    the audio. Any connector that only introduced the citation ("according to", "as
    mentioned in", a dangling "in") is removed with it, and passive-aggressive "as I said
    earlier" phrases are dropped, so no broken or toxic phrase is left in the audio.
    """
    stripped = _CITATION_PATTERN.sub("", text)
    stripped = _BANNED_SPOKEN.sub(" ", stripped)
    stripped = re.sub(r"\s+([.,;:!?])", r"\1", stripped)   # tidy space left before punctuation
    stripped = re.sub(r"\(\s*\)", "", stripped)            # drop any now-empty parentheses
    stripped = re.sub(r"^[\s,;:]+", "", stripped)          # no leading comma left by a removal
    return re.sub(r"\s{2,}", " ", stripped).strip()


# Public alias for reuse (e.g. cleaning streamed sentences before TTS).
strip_citations = _spoken


_GROUNDING_RULES = (
    "Answer using ONLY the knowledge base. To find information, call the "
    "search_knowledge_base tool with a focused query. Base your answer strictly on the "
    "returned passages — do not use outside knowledge. Cite every fact with its source "
    "filename in square brackets exactly as shown, e.g. [interview_process.md]. If the "
    "passages do not contain the answer, ask one useful clarifying question or offer "
    "escalation; do not mention the knowledge base to the caller. "
    "Speak in one or two short spoken sentences: say the information as if you simply know it "
    "— never narrate your sources or say 'according to', 'the guide', 'the document', 'as I "
    "mentioned', or 'as I said' — and do not repeat the caller's words back to them. You cannot "
    "perform actions for the caller — never claim you did something ('I've done', 'I've gone "
    "ahead'); ask them to do each step. If the caller just answered you, act on their answer "
    "instead of asking them to confirm it. If the caller did not understand, re-explain your "
    "last point far more simply as one concrete micro-step; never just repeat the same sentence."
)


@dataclass(frozen=True, slots=True)
class Citation:
    """Where a cited answer came from — for the dashboard transcript and debugging.

    One per cited source, aggregating the provenance of the retrieved chunks from that
    source (page numbers, section heading) so the caller-facing transcript can show
    ``guide.pdf — Managing authentication factors (p17)`` instead of a bare filename.
    """

    source: str
    pages: list[int] = field(default_factory=list)     # distinct pages, ascending
    heading: str = ""                                  # heading of the best-scoring chunk
    chunk_ids: list[str] = field(default_factory=list)
    score: float | None = None                         # best rerank score among the chunks

    def label(self) -> str:
        text = self.source
        if self.heading:
            text += f" — {self.heading}"
        if self.pages:
            text += " (" + ", ".join(f"p{page}" for page in self.pages) + ")"
        return text

    def to_dict(self) -> dict:
        data: dict = {"source": self.source, "label": self.label()}
        if self.pages:
            data["pages"] = list(self.pages)
        if self.heading:
            data["heading"] = self.heading
        if self.chunk_ids:
            data["chunk_ids"] = list(self.chunk_ids)
        if self.score is not None:
            data["score"] = round(self.score, 4)
        return data


def build_citations(text: str, retrieved: list[ScoredChunk]) -> list[Citation]:
    """Group the chunks the model cited (by ``[source]``) into rich, per-source citations."""
    grouped: dict[str, list[ScoredChunk]] = {}
    for scored in retrieved:
        source = scored.chunk.source
        if f"[{source}]" in text:
            grouped.setdefault(source, []).append(scored)

    citations: list[Citation] = []
    for source, chunks in sorted(grouped.items()):
        ranked = sorted(chunks, key=lambda c: c.score, reverse=True)
        pages = sorted(
            {c.chunk.metadata["page"] for c in ranked if c.chunk.metadata.get("page") is not None}
        )
        headings = [h for h in (c.chunk.metadata.get("heading") for c in ranked) if h]
        citations.append(
            Citation(
                source=source,
                pages=pages,
                heading=headings[0] if headings else "",
                chunk_ids=[c.chunk.id for c in ranked],
                score=ranked[0].score if ranked else None,
            )
        )
    return citations


@dataclass(slots=True)
class GroundedAnswer:
    text: str
    citations: list[str]                       # source filenames cited in the answer
    retrieved: list[ScoredChunk] = field(default_factory=list)
    tool_calls: int = 0
    details: list[Citation] = field(default_factory=list)  # per-source page/heading provenance


class GroundedResponder:
    def __init__(
        self,
        llm: LLMProvider,
        retriever: Retriever,
        *,
        system_prompt: str,
        max_tool_iters: int = 3,
        min_confidence: float = 0.0,
        fallback_message: str | None = None,
    ) -> None:
        self._llm = llm
        self._retriever = retriever
        self._system_prompt = f"{system_prompt}\n\n{_GROUNDING_RULES}"
        self._max_tool_iters = max_tool_iters
        self._min_confidence = min_confidence  # grounding gate (0.0 = off)
        # Deterministic reply when nothing confident is retrieved. Domain-configurable
        # (DomainConfig.fallback_prompt) so wording fits the vertical; the default is
        # domain-neutral and, per policy, never mentions the "knowledge base" to the caller.
        self._fallback_message = (fallback_message or "").strip() or refusal_message()

    @staticmethod
    def _format_context(chunks: list[ScoredChunk]) -> str:
        if not chunks:
            return "No relevant documents were found."
        return "\n\n".join(f"[{c.chunk.source}] {c.chunk.text}" for c in chunks)

    async def _retrieve_confident(self, query: str) -> tuple[list[ScoredChunk], int]:
        """Retrieve for ``query`` and keep only chunks past the grounding gate."""
        chunks = await asyncio.to_thread(self._retriever.retrieve, query)
        confident = [c for c in chunks if is_grounded(c.score, self._min_confidence)]
        log.info(
            "retrieve-then-read query=%r -> %d chunks (%d confident)",
            query, len(chunks), len(confident),
        )
        return confident, len(chunks)

    def _read_messages(self, question: str, chunks: list[ScoredChunk]) -> list[Message]:
        """Prompt for the read step: the caller context plus the retrieved passages."""
        user = (
            f"{question}\n\nKnowledge base passages — answer using ONLY these and cite each "
            f"fact with its [source] exactly as shown:\n{self._format_context(chunks)}"
        )
        return [Message(Role.SYSTEM, self._system_prompt), Message(Role.USER, user)]

    async def _grounded_read(self, question: str, query: str) -> GroundedAnswer:
        """Retrieve on ``query``, then read the passages (no tool calling).

        Used for caller-led flows (a clean search query is supplied) and as the
        fallback when the model can't do function calling — grounding (retrieve +
        confidence gate) is preserved either way.
        """
        confident, n_retrieved = await self._retrieve_confident(query)
        latency.observe(retrieved_chunks_count=n_retrieved, confident_chunks_count=len(confident))
        if not confident:
            return GroundedAnswer(text=self._fallback_message, citations=[], tool_calls=0)
        with latency.span("llm_total_ms"):
            response = await self._llm.chat(self._read_messages(question, confident))
        return self._finalize(response.text, confident, tool_calls=0)

    async def answer(self, question: str, *, search_query: str | None = None) -> GroundedAnswer:
        # Retrieve-then-read: when the caller supplies a clean search query (caller-led flows),
        # retrieve first and let the model read the passages — it never skips retrieval, so a
        # grounded answer is not silently replaced by the deterministic fallback.
        if search_query:
            return await self._grounded_read(question, search_query)
        try:
            return await self._answer_via_tools(question)
        except ProviderError as exc:
            # Some models fail hard on function calling (e.g. Groq `tool_use_failed`).
            # Degrade to a deterministic retrieve-then-read on the raw question instead of
            # failing the whole call; grounding is preserved.
            log.warning("grounded tool calling failed (%s); retrieve-then-read fallback", exc)
            return await self._grounded_read(question, question)

    async def _answer_via_tools(self, question: str) -> GroundedAnswer:
        """Model-driven retrieval: give it the search tool and let it decide when to search."""
        messages = [Message(Role.SYSTEM, self._system_prompt), Message(Role.USER, question)]
        retrieved: list[ScoredChunk] = []
        tool_calls = 0
        n_retrieved = 0

        for _ in range(self._max_tool_iters):
            with latency.span("llm_total_ms"):
                response = await self._llm.chat(messages, tools=[SEARCH_TOOL])
            if not response.tool_calls:
                latency.observe(
                    retrieved_chunks_count=n_retrieved, confident_chunks_count=len(retrieved)
                )
                return self._finalize(response.text, retrieved, tool_calls)

            messages.append(Message(Role.ASSISTANT, response.text, tool_calls=response.tool_calls))
            for call in response.tool_calls:
                tool_calls += 1
                query = str(call.arguments.get("query") or question)
                chunks = await asyncio.to_thread(self._retriever.retrieve, query)
                n_retrieved += len(chunks)
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
        with latency.span("llm_total_ms"):
            final = await self._llm.chat(messages)
        latency.observe(retrieved_chunks_count=n_retrieved, confident_chunks_count=len(retrieved))
        return self._finalize(final.text, retrieved, tool_calls)

    async def _grounded_read_streaming(self, question: str, query: str):
        """Streaming counterpart of :meth:`_grounded_read`."""
        confident, n = await self._retrieve_confident(query)
        latency.observe(retrieved_chunks_count=n, confident_chunks_count=len(confident))
        if not confident:
            yield self._fallback_message
            return
        answer_start = time.perf_counter()
        first = True
        async for delta in self._llm.chat_stream(self._read_messages(question, confident)):
            if first:
                latency.observe(llm_ttft_ms=(time.perf_counter() - answer_start) * 1000.0)
                first = False
            yield delta

    async def answer_streaming(self, question: str, *, search_query: str | None = None):
        """Stream the grounded answer as raw text deltas (with ``[source]`` markers).

        Same retrieval + deterministic-refusal logic as :meth:`answer`, but the
        FINAL answer is produced with ``chat_stream`` so audio can start before the
        whole answer is written. Citation stripping happens downstream, per sentence.
        """
        # Retrieve-then-read fast path (caller-led flows): ground on the clean query first.
        if search_query:
            async for delta in self._grounded_read_streaming(question, search_query):
                yield delta
            return
        # Tool-driven path, with the same fail-hard-on-function-calling fallback as answer().
        # The tool call (which is what fails) happens before any delta is yielded, so a
        # fallback here never double-streams; guard with `yielded` just in case.
        yielded = False
        try:
            async for delta in self._answer_via_tools_streaming(question):
                yielded = True
                yield delta
        except ProviderError as exc:
            if yielded:
                raise
            log.warning("grounded tool calling failed (%s); retrieve-then-read fallback", exc)
            async for delta in self._grounded_read_streaming(question, question):
                yield delta

    async def _answer_via_tools_streaming(self, question: str):
        messages = [Message(Role.SYSTEM, self._system_prompt), Message(Role.USER, question)]
        retrieved: list[ScoredChunk] = []
        n_retrieved = 0

        for _ in range(self._max_tool_iters):
            with latency.span("llm_total_ms"):
                response = await self._llm.chat(messages, tools=[SEARCH_TOOL])
            if not response.tool_calls:
                break  # the model is ready to answer
            messages.append(Message(Role.ASSISTANT, response.text, tool_calls=response.tool_calls))
            for call in response.tool_calls:
                query = str(call.arguments.get("query") or question)
                chunks = await asyncio.to_thread(self._retriever.retrieve, query)
                n_retrieved += len(chunks)
                confident = [c for c in chunks if is_grounded(c.score, self._min_confidence)]
                retrieved.extend(confident)
                messages.append(
                    Message(Role.TOOL, self._format_context(confident),
                            tool_call_id=call.id, name=call.name)
                )

        latency.observe(retrieved_chunks_count=n_retrieved, confident_chunks_count=len(retrieved))
        if not retrieved:  # deterministic refusal — never stream an ungrounded answer
            yield self._fallback_message
            return
        # llm_ttft: the answer LLM's own time-to-first-token (unaffected by downstream
        # backpressure, since the first token is pulled immediately).
        answer_start = time.perf_counter()
        first = True
        async for delta in self._llm.chat_stream(messages):
            if first:
                latency.observe(llm_ttft_ms=(time.perf_counter() - answer_start) * 1000.0)
                first = False
            yield delta

    def _finalize(
        self, raw_text: str, retrieved: list[ScoredChunk], tool_calls: int
    ) -> GroundedAnswer:
        # Deterministic grounding: with no confident chunk, refuse — never trust the
        # LLM to have refused on its own (guarantees "no answer outside the KB").
        if not retrieved:
            return GroundedAnswer(text=self._fallback_message, citations=[], tool_calls=tool_calls)
        # Citations are parsed from the raw model text; the spoken text has them stripped.
        details = build_citations(raw_text, retrieved)
        return GroundedAnswer(
            text=_spoken(raw_text),
            citations=[c.source for c in details],
            retrieved=retrieved,
            tool_calls=tool_calls,
            details=details,
        )
