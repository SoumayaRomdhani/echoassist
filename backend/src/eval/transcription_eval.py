"""Transcription accuracy (WER) on clean vs telephonized audio.

    python -m src.eval.transcription_eval

For each reference sentence: synthesize it (TTS), transcribe the clean audio,
telephonize it (8 kHz band-pass µ-law) and transcribe that, then report the word
error rate against the reference. Shows how much narrowband telephony degrades
STT (ROADMAP §Sprint 5). Fully local — TTS + ffmpeg + STT, no API/quota.
Requires ffmpeg on PATH.
"""

from __future__ import annotations

import argparse
import asyncio
import re

from config.settings import build_stt, build_tts, get_settings
from src.audio.io import chunk_to_float, resample, telephonize, write_wav
from src.console import bold, dim, init_console
from src.log import setup_logging

_REFERENCES = [
    "I have about six years of experience as a backend Python developer.",
    "I am available to start within a month and I am comfortable working remotely.",
    "My main stack is Python with FastAPI and PostgreSQL for the database.",
]


def _normalize(text: str) -> list[str]:
    return re.sub(r"[^a-z0-9\s]", " ", text.lower()).split()


def word_error_rate(reference: str, hypothesis: str) -> float:
    """Word-level edit distance / reference length."""
    ref, hyp = _normalize(reference), _normalize(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        curr = [i]
        for j, h in enumerate(hyp, 1):
            cost = 0 if r == h else 1
            curr.append(min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost))
        prev = curr
    return prev[-1] / len(ref)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Transcription WER (clean vs telephonized).")
    parser.parse_args()

    settings = get_settings()
    init_console()
    setup_logging(settings.log_level)
    work = settings.data_dir / "test_audio"

    tts, stt = build_tts(settings), build_stt(settings)
    clean_scores: list[float] = []
    tel_scores: list[float] = []

    print(bold(f"\nTranscription WER — {len(_REFERENCES)} sentences\n"))
    for i, reference in enumerate(_REFERENCES):
        chunk = await tts.synthesize(reference)
        clean_wav = work / f"wer_{i}_clean.wav"
        tel_wav = work / f"wer_{i}_tel.wav"
        write_wav(clean_wav, resample(chunk_to_float(chunk), chunk.fmt.sample_rate, 16000), 16000)
        telephonize(clean_wav, tel_wav)

        clean_hyp = (await stt.transcribe(chunk)).text
        tel_hyp = (await stt.transcribe(await _load(tel_wav))).text
        clean_wer = word_error_rate(reference, clean_hyp)
        tel_wer = word_error_rate(reference, tel_hyp)
        clean_scores.append(clean_wer)
        tel_scores.append(tel_wer)

        print(f"  ref:   {reference}")
        print(dim(f"  clean (WER {clean_wer:.2f}): {clean_hyp}"))
        print(dim(f"  tel   (WER {tel_wer:.2f}): {tel_hyp}\n"))

    mean_clean = sum(clean_scores) / len(clean_scores)
    mean_tel = sum(tel_scores) / len(tel_scores)
    print(bold(f"mean WER  clean={mean_clean:.3f}   telephonized={mean_tel:.3f}\n"))


async def _load(path):
    from src.audio.io import chunk_from_float, read_wav

    samples, sr = read_wav(path)
    return chunk_from_float(resample(samples, sr, 16000), 16000)


if __name__ == "__main__":
    asyncio.run(main())
