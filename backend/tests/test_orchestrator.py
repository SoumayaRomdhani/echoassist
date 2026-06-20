"""Speaking-loop + consent-gate orchestration, validated with fake providers."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from src.agent.consent import ConsentDecision
from src.agent.domain import DomainConfig
from src.agent.orchestrator import VoicePipeline
from src.providers.llm.base import LLMProvider
from src.providers.stt.base import STTProvider
from src.providers.tts.base import TTSProvider
from src.providers.types import (
    AudioChunk,
    AudioFormat,
    LLMResponse,
    Message,
    Role,
    Transcript,
)

_FMT = AudioFormat(sample_rate=16000)


def _audio() -> AudioChunk:
    return AudioChunk(data=b"\x00\x00" * 160, fmt=_FMT)


class FakeSTT(STTProvider):
    """Returns queued transcripts in order; repeats the last one when exhausted."""

    def __init__(self, transcripts: str | list[str]) -> None:
        self._queue = [transcripts] if isinstance(transcripts, str) else list(transcripts)

    async def transcribe_stream(
        self, audio: AsyncIterator[AudioChunk]
    ) -> AsyncIterator[Transcript]:
        async for _ in audio:  # drain like a real provider
            pass
        text = self._queue[0] if self._queue else ""
        if len(self._queue) > 1:  # keep the last transcript for any further calls
            self._queue.pop(0)
        yield Transcript(text=text, is_final=True)


class FakeLLM(LLMProvider):
    def __init__(self, reply: str = "Tell me more.") -> None:
        self._reply = reply
        self.seen: list[Message] = []

    async def chat(self, messages, tools=None) -> LLMResponse:
        self.seen = list(messages)
        return LLMResponse(text=self._reply)


class FakeTTS(TTSProvider):
    @property
    def output_format(self) -> AudioFormat:
        return AudioFormat(sample_rate=24000)

    async def synthesize_stream(self, text: str) -> AsyncIterator[AudioChunk]:
        yield AudioChunk(data=text.encode("utf-8"), fmt=self.output_format)


def _domain() -> DomainConfig:
    return DomainConfig(
        name="screening",
        language="en",
        disclosure="This is an AI assistant. Do you consent to continue?",
        greeting="Thanks, let's begin.",
        system_prompt="You are a concise screening assistant.",
        consent_reprompt="Sorry, is that a yes or a no?",
        consent_decline="No problem, goodbye.",
    )


def _pipeline(
    transcripts: str | list[str], reply: str = "Tell me more."
) -> tuple[VoicePipeline, FakeLLM]:
    llm = FakeLLM(reply)
    return VoicePipeline(FakeSTT(transcripts), llm, FakeTTS(), _domain()), llm


@pytest.mark.asyncio
async def test_disclosure_is_spoken_without_the_greeting() -> None:
    pipeline, _ = _pipeline("yes")
    text, audio = await pipeline.speak_disclosure()
    assert "consent" in text.lower()
    assert "let's begin" not in text.lower()  # greeting withheld until consent
    assert audio.data


@pytest.mark.asyncio
async def test_consent_accepted_speaks_greeting_and_allows_interview() -> None:
    pipeline, llm = _pipeline(["yes, that's fine", "I have five years of experience"])
    await pipeline.speak_disclosure()

    consent = await pipeline.handle_consent(_audio())
    assert consent.decision is ConsentDecision.ACCEPTED
    assert consent.proceed is True
    assert consent.ended is False
    assert consent.reply == "Thanks, let's begin."
    assert pipeline.consent_granted is True

    result = await pipeline.run_turn(_audio())
    assert result.reply == "Tell me more."
    assert any(m.role is Role.USER and "five years" in m.content for m in llm.seen)


@pytest.mark.asyncio
async def test_consent_refused_declines_and_ends_call() -> None:
    pipeline, _ = _pipeline("no, I'd rather not")
    await pipeline.speak_disclosure()

    consent = await pipeline.handle_consent(_audio())
    assert consent.decision is ConsentDecision.REFUSED
    assert consent.proceed is False
    assert consent.ended is True
    assert consent.reply == "No problem, goodbye."
    assert pipeline.consent_granted is False


@pytest.mark.asyncio
async def test_repeated_ambiguous_consent_reprompts_then_ends() -> None:
    pipeline, _ = _pipeline(["who is this?", "hmm maybe"])
    await pipeline.speak_disclosure()

    first = await pipeline.handle_consent(_audio())
    assert first.decision is ConsentDecision.AMBIGUOUS
    assert first.ended is False and first.proceed is False
    assert first.reply == "Sorry, is that a yes or a no?"  # re-asked

    second = await pipeline.handle_consent(_audio())
    assert second.decision is ConsentDecision.AMBIGUOUS
    assert second.ended is True  # second unclear answer ends the call
    assert second.reply == "No problem, goodbye."
    assert pipeline.consent_granted is False


@pytest.mark.asyncio
async def test_run_turn_before_consent_is_rejected() -> None:
    pipeline, _ = _pipeline("anything")
    await pipeline.speak_disclosure()
    with pytest.raises(RuntimeError):
        await pipeline.run_turn(_audio())
