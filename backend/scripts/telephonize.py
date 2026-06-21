"""Telephonize a WAV file to PSTN characteristics for realistic testing.

Applies what a phone line does to audio: 8 kHz, band-pass 300-3400 Hz, G.711
µ-law (ARCHITECTURE.md §6, ROADMAP §1). The core lives in `src.audio.io`.

    python scripts/telephonize.py in.wav out.wav
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.audio.io import telephonize


def main() -> None:
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
