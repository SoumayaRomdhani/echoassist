"""Per-stage latency eval (p50 / p95).

    python -m src.eval.latency_eval [--iters 5] [--with-llm]

Times each pipeline stage that runs locally — STT, retrieval (embed + hybrid
search + rerank), TTS — over N iterations and reports p50/p95/mean. The LLM
stage is optional (it costs Gemini quota). Models are warmed up once before
timing so load time is excluded.

Target is < 800 ms/turn (ARCHITECTURE.md §9) — realistic only with a GPU and
streaming. On CPU the STT stage dominates; this harness makes that measurable.
Requires Qdrant running + the domain ingested.
"""

from __future__ import annotations

import argparse
import asyncio
import math
import time
from collections.abc import AsyncIterator

from config.settings import build_llm, build_retriever, build_stt, build_tts, get_settings
from src.agent.streaming import synthesize_streaming
from src.audio.io import chunk_from_float, read_wav, resample
from src.console import bold, dim, init_console
from src.log import setup_logging
from src.providers.errors import ProviderError
from src.providers.types import AudioChunk, Message, Role


def percentile(values: list[float], p: float) -> float:
    """Linear-interpolation percentile (p in 0..100)."""
    if not values:
        return 0.0
    ordered = sorted(values)
    k = (len(ordered) - 1) * (p / 100.0)
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return ordered[int(k)]
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def _report(stage: str, samples: list[float]) -> float:
    p50, p95 = percentile(samples, 50), percentile(samples, 95)
    mean = sum(samples) / len(samples)
    print(f"  {stage:<10} p50={p50:7.0f}ms  p95={p95:7.0f}ms  mean={mean:7.0f}ms")
    return p50


async def _time(coro_factory, iters: int) -> list[float]:
    await coro_factory()  # warm-up (load model), excluded
    samples = []
    for _ in range(iters):
        start = time.perf_counter()
        await coro_factory()
        samples.append((time.perf_counter() - start) * 1000)
    return samples


async def main() -> None:
    parser = argparse.ArgumentParser(description="Per-stage latency eval (p50/p95).")
    parser.add_argument("--iters", type=int, default=5)
    parser.add_argument("--with-llm", action="store_true", help="Also time the LLM (uses quota).")
    args = parser.parse_args()

    settings = get_settings()
    init_console()
    setup_logging(settings.log_level)

    audio_path = settings.data_dir / "test_audio" / "sample_consent.wav"
    if not audio_path.exists():
        raise SystemExit("Missing sample audio — run: python scripts/gen_sample_audio.py")
    samples, sr = read_wav(audio_path)
    chunk: AudioChunk = chunk_from_float(resample(samples, sr, 16000), 16000)

    stt, retriever, tts = build_stt(settings), build_retriever(settings), build_tts(settings)
    query = "What is the salary range for the backend role?"
    # Multi-sentence so TTFA (first sentence) is visibly lower than full TTS.
    reply = (
        "The base salary range is 65,000 to 85,000 euros per year. "
        "It depends on your experience and location. "
        "The role is also fully remote within the EU."
    )

    print(bold(f"\nLatency eval — {args.iters} iterations (after warm-up)\n"))
    p50s = {}
    p50s["stt"] = _report("STT", await _time(lambda: stt.transcribe(chunk), args.iters))
    p50s["retrieval"] = _report(
        "retrieval", await _time(lambda: asyncio.to_thread(retriever.retrieve, query), args.iters)
    )
    p50s["tts"] = _report("TTS(full)", await _time(lambda: tts.synthesize(reply), args.iters))

    async def _reply_deltas() -> AsyncIterator[str]:
        for word in reply.split(" "):  # simulate the LLM emitting the reply in deltas
            yield word + " "

    async def tts_stream_first() -> None:
        async for _ in synthesize_streaming(_reply_deltas(), tts):
            return  # first audio = after the first sentence, not the whole reply

    ttfa_tts = _report("TTFA-TTS(sim)", await _time(tts_stream_first, args.iters))

    ttfa_real = None
    if args.with_llm:
        llm = build_llm(settings)
        p50s["llm"] = _report(
            "LLM", await _time(lambda: llm.chat([Message(Role.USER, query)]), args.iters)
        )

        async def llm_tts_first() -> None:  # real LLM stream -> TTS first audio
            async for _ in synthesize_streaming(llm.chat_stream([Message(Role.USER, query)]), tts):
                return

        ttfa_real = _report("TTFA(LLM→TTS)", await _time(llm_tts_first, args.iters))

    total = sum(p50s.values())
    print(bold(f"\n  full turn (sum of p50s) = {total:.0f} ms"))
    print(dim(f"  TTFA-TTS(simulated deltas) = {ttfa_tts:.0f} ms  — TTS-only, excludes STT + LLM"))
    if ttfa_real is not None:
        perceived = p50s["stt"] + ttfa_real
        print(bold(f"  perceived first-audio ≈ STT + TTFA(LLM→TTS) = {perceived:.0f} ms"))
    else:
        print(dim("  (run with --with-llm for the REAL perceived first-audio: STT + LLM→TTS)"))
    print(dim("  Target < 800 ms/turn (ARCHITECTURE.md §9) is realistic only with a GPU."))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except ProviderError as exc:
        from src.console import FAIL

        raise SystemExit(f"{FAIL} {exc}") from exc
