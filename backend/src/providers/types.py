"""Shared, dependency-light value types exchanged across provider interfaces.

These types are the contract between providers and business logic. They use only
the standard library so they can be imported anywhere (API, tests, doctor)
without pulling in numpy or any ML dependency.

Audio convention across the codebase: raw PCM, signed 16-bit, little-endian,
mono — described by :class:`AudioFormat`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


# --------------------------------------------------------------------------- #
# Audio                                                                       #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class AudioFormat:
    """Describes a raw PCM stream."""

    sample_rate: int
    channels: int = 1
    sample_width: int = 2  # bytes per sample (16-bit PCM)


@dataclass(frozen=True, slots=True)
class AudioChunk:
    """A block of raw PCM16 audio plus its format."""

    data: bytes
    fmt: AudioFormat

    @property
    def num_samples(self) -> int:
        return len(self.data) // (self.fmt.sample_width * self.fmt.channels)

    @property
    def duration_s(self) -> float:
        if self.fmt.sample_rate == 0:
            return 0.0
        return self.num_samples / self.fmt.sample_rate


# --------------------------------------------------------------------------- #
# STT                                                                         #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class Transcript:
    """A speech-to-text result. ``is_final=False`` marks an interim hypothesis."""

    text: str
    is_final: bool = True
    language: str | None = None
    confidence: float | None = None
    start_s: float | None = None
    end_s: float | None = None


# --------------------------------------------------------------------------- #
# LLM                                                                         #
# --------------------------------------------------------------------------- #
class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass(slots=True)
class Message:
    """A single conversation message."""

    role: Role
    content: str
    # Set on TOOL-role messages to correlate a tool result with its call (Sprint 2+).
    tool_call_id: str | None = None
    name: str | None = None


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """A tool the LLM may call, described with a JSON-Schema parameter object."""

    name: str
    description: str
    parameters: dict


@dataclass(frozen=True, slots=True)
class ToolCall:
    """A tool invocation requested by the model."""

    id: str
    name: str
    arguments: dict


@dataclass(slots=True)
class LLMResponse:
    """An LLM turn result: spoken text and/or tool calls."""

    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str | None = None
    usage: dict | None = None
