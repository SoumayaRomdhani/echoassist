"""Telephonize a WAV file to PSTN characteristics for realistic testing.

Applies what a phone line does to audio: downsample to 8 kHz, band-pass to the
300-3400 Hz voice band, and encode as G.711 µ-law. Use this on clean test audio
so STT/latency evals reflect real call quality (ARCHITECTURE.md §6, ROADMAP §1).

Usage:
    python scripts/telephonize.py in.wav out.wav
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from src.console import init_console

# 8 kHz, band-pass 300-3400 Hz, µ-law — the classic narrowband telephony profile.
_FILTER = "highpass=f=300,lowpass=f=3400"
_SAMPLE_RATE = "8000"
_CODEC = "pcm_mulaw"


def telephonize(src: Path, dst: Path) -> None:
    """Run ffmpeg to telephonize ``src`` into ``dst`` (a µ-law WAV)."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError(
            "ffmpeg not found on PATH. Install it (Windows: `winget install Gyan.FFmpeg`) "
            "and reopen your shell."
        )
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(src),
        "-ar", _SAMPLE_RATE,
        "-ac", "1",
        "-af", _FILTER,
        "-c:a", _CODEC,
        str(dst),
    ]
    subprocess.run(cmd, check=True)


def main() -> None:
    init_console()
    parser = argparse.ArgumentParser(description="Telephonize a WAV (8 kHz band-pass µ-law).")
    parser.add_argument("src", type=Path, help="Input WAV file.")
    parser.add_argument("dst", type=Path, help="Output (telephonized) WAV file.")
    args = parser.parse_args()

    if not args.src.exists():
        sys.exit(f"Input not found: {args.src}")
    telephonize(args.src, args.dst)
    print(f"telephonized {args.src} -> {args.dst}  (8kHz, 300-3400Hz, µ-law)")


if __name__ == "__main__":
    main()
