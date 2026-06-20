"""Voice pipeline orchestrator — the Sprint 1 speaking loop with a consent gate.

Call lifecycle:
  1. ``speak_disclosure()``  — mandatory spoken AI disclosure (asks for consent).
  2. ``handle_consent(audio)`` — transcribe the caller, classify yes/no/unclear:
        accepted  -> speak the greeting, the interview may proceed
        refused   -> speak a decline message, the call must end
        ambiguous -> re-ask once; a second unclear answer ends the call
  3. ``run_turn(audio)``     — an interview turn (only valid once consent granted).

It stays provider-agnostic (knows only the base interfaces) and tracks per-stage
latency so Sprint 5 has measurements to optimise.

Design note (Pipecat): the architecture names Pipecat as the orchestration layer.
Its value — turn-taking, barge-in, live transport — is exercised from Sprint 3
(interruption) and Sprint 8 (telephony). Sprint 1 only needs a file-in /
speech-out loop over replayed audio, so :class:`VoicePipeline` owns a clean,
testable turn loop here; ``run_turn`` / ``handle_consent`` are the units a Pipecat
FrameProcessor will wrap when live turn-taking lands.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from src.agent.consent import ConsentDecision, classify_consent
from src.agent.dialogue import DialogueManager
from src.agent.domain import DomainConfig
from src.providers.llm.base import LLMProvider
from src.providers.stt.base import STTProvider
from src.providers.tts.base import TTSProvider
from src.providers.types import AudioChunk, Message, Role

log = logging.getLogger("echoassist.orchestrator")

_FALLBACK_REPLY = "Sorry, I didn't catch that. Could you say it again?"


@dataclass(frozen=True, slots=True)
class Timings:
    """Per-stage wall-clock latency for one turn, in milliseconds."""

    stt_ms: float
    llm_ms: float
    tts_ms: float

    @property
    def total_ms(self) -> float:
        return self.stt_ms + self.llm_ms + self.tts_ms


@dataclass(slots=True)
class TurnResult:
    transcript: str
    reply: str
    audio: AudioChunk
    timings: Timings


@dataclass(slots=True)
class ConsentTurn:
    """Outcome of one consent exchange."""

    transcript: str
    decision: ConsentDecision
    reply: str            # what the agent speaks next (greeting / reprompt / decline)
    audio: AudioChunk
    proceed: bool         # consent granted -> the interview may continue
    ended: bool           # the call must end (refused, or repeated ambiguity)


@dataclass(slots=True)
class InterviewTurn:
    """Outcome of one interview turn (Sprint 3)."""

    transcript: str
    reply: str
    audio: AudioChunk
    ended: bool
    citations: list[str] = field(default_factory=list)


class VoicePipeline:
    """Stateful conversation pipeline for a single call."""

    def __init__(
        self,
        stt: STTProvider,
        llm: LLMProvider,
        tts: TTSProvider,
        domain: DomainConfig,
        *,
        dialogue: DialogueManager | None = None,
        max_history_messages: int = 20,
        max_consent_attempts: int = 2,
    ) -> None:
        self._stt = stt
        self._llm = llm
        self._tts = tts
        self._domain = domain
        self._dialogue = dialogue
        self._max_history = max_history_messages
        self._max_consent_attempts = max_consent_attempts
        self._consent_attempts = 0
        self._consent_granted = False
        self._history: list[Message] = [Message(Role.SYSTEM, domain.system_prompt)]

    @property
    def consent_granted(self) -> bool:
        return self._consent_granted

    # --- call lifecycle ----------------------------------------------------
    async def speak_disclosure(self) -> tuple[str, AudioChunk]:
        """Speak the mandatory AI disclosure at call start (ARCHITECTURE.md §10).

        The disclosure asks for consent; the greeting is withheld until the caller
        explicitly agrees in :meth:`handle_consent`.
        """
        text = self._domain.disclosure
        return text, await self._say(text)

    async def handle_consent(self, audio) -> ConsentTurn:
        """Process the caller's answer to the consent question.

        ``audio`` is an :class:`AudioChunk` or an async iterator of them.
        """
        transcript = await self._stt.transcribe(audio)
        self._history.append(Message(Role.USER, transcript.text))
        decision = classify_consent(transcript.text)
        log.info("consent: decision=%s transcript=%r", decision.value, transcript.text)

        if decision is ConsentDecision.ACCEPTED:
            self._consent_granted = True
            reply, proceed, ended = self._domain.greeting or "Thank you.", True, False
        elif decision is ConsentDecision.REFUSED:
            reply, proceed, ended = self._domain.consent_decline, False, True
        else:
            # Ambiguous: re-ask once; a second unclear answer ends the call.
            self._consent_attempts += 1
            if self._consent_attempts >= self._max_consent_attempts:
                reply, proceed, ended = self._domain.consent_decline, False, True
            else:
                reply, proceed, ended = self._domain.consent_reprompt, False, False

        audio_out = await self._say(reply)
        return ConsentTurn(transcript.text, decision, reply, audio_out, proceed, ended)

    async def run_turn(self, audio) -> TurnResult:
        """Process one interview utterance: transcribe, answer, synthesize the reply.

        Only valid after consent is granted; calling it earlier is a programming error.
        """
        if not self._consent_granted:
            raise RuntimeError("run_turn() called before consent was granted")

        t0 = time.perf_counter()
        transcript = await self._stt.transcribe(audio)
        t1 = time.perf_counter()

        self._history.append(Message(Role.USER, transcript.text))
        response = await self._llm.chat(self._windowed_history())
        reply = response.text.strip() or _FALLBACK_REPLY
        self._history.append(Message(Role.ASSISTANT, reply))
        t2 = time.perf_counter()

        reply_audio = await self._tts.synthesize(reply)
        t3 = time.perf_counter()

        timings = Timings(
            stt_ms=(t1 - t0) * 1000,
            llm_ms=(t2 - t1) * 1000,
            tts_ms=(t3 - t2) * 1000,
        )
        log.info(
            "turn done | stt=%.0fms llm=%.0fms tts=%.0fms total=%.0fms",
            timings.stt_ms,
            timings.llm_ms,
            timings.tts_ms,
            timings.total_ms,
        )
        return TurnResult(transcript.text, reply, reply_audio, timings)

    # --- interview (Sprint 3) ---------------------------------------------
    async def begin_interview(self) -> tuple[str, AudioChunk]:
        """Speak the interviewer's first question (after consent + greeting)."""
        self._require_dialogue()
        text = await self._dialogue.start()
        return text, await self.speak(text)

    async def interview_turn(self, audio) -> InterviewTurn:
        """Process one interview utterance: transcribe -> dialogue decision -> speak."""
        self._require_dialogue()
        transcript = await self._stt.transcribe(audio)
        turn = await self._dialogue.handle_turn(transcript.text)
        audio_out = await self.speak(turn.text)
        return InterviewTurn(transcript.text, turn.text, audio_out, turn.ended, turn.citations)

    async def speak(self, text: str) -> AudioChunk:
        """Synthesize agent speech (no conversation-history side effects)."""
        return await self._tts.synthesize(text)

    def _require_dialogue(self) -> None:
        if self._dialogue is None:
            raise RuntimeError("VoicePipeline was constructed without a DialogueManager")

    # --- internals ---------------------------------------------------------
    async def _say(self, text: str) -> AudioChunk:
        """Record an agent line in history and synthesize it."""
        self._history.append(Message(Role.ASSISTANT, text))
        return await self._tts.synthesize(text)

    def _windowed_history(self) -> list[Message]:
        """System prompt + the most recent N messages (keeps prompt size bounded)."""
        system, rest = self._history[0], self._history[1:]
        return [system, *rest[-self._max_history :]]

    async def aclose(self) -> None:
        for provider in (self._stt, self._llm, self._tts):
            await provider.aclose()
