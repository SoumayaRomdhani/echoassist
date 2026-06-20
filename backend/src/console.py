"""Cross-platform console output helpers.

Windows consoles default to a legacy code page (cp1252) that cannot encode the
status glyphs we print, and ANSI colour codes are just noise when output is
piped to a file. :func:`init_console` forces UTF-8; the style helpers emit
colour/emoji only on a real terminal and fall back to ASCII otherwise.
"""

from __future__ import annotations

import contextlib
import sys


def init_console() -> None:
    """Force UTF-8 on stdout/stderr so non-ASCII output never crashes."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            with contextlib.suppress(Exception):  # best-effort; plain encoding is acceptable
                reconfigure(encoding="utf-8")


_COLOR = bool(getattr(sys.stdout, "isatty", lambda: False)())


def _wrap(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOR else text


def bold(text: str) -> str:
    return _wrap("1", text)


def dim(text: str) -> str:
    return _wrap("2", text)


# Status markers: coloured glyphs on a TTY, ASCII tags when redirected.
OK = _wrap("32", "✅") if _COLOR else "[ OK ]"
WARN = _wrap("33", "⚠") if _COLOR else "[WARN]"
FAIL = _wrap("31", "✗") if _COLOR else "[FAIL]"
