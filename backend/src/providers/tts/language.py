"""Lightweight French/English detection for per-utterance TTS voice selection.

A TTS voice speaks one language, so to mirror the caller's language a provider must
pick the matching voice for each reply. We only distinguish the two languages this
product speaks, so a light heuristic is enough — no extra dependency. French is
accent-dense, so accented characters catch almost every real French sentence; a small
set of accent-free French function words covers short replies ("oui", "bonjour",
"merci") that carry no diacritic. Anything else stays English, which keeps the fixed
English lines (disclosure, greeting, canned questions, fillers) on the English voice.
"""

from __future__ import annotations

import re

_FRENCH_ACCENTS = re.compile(r"[àâäçéèêëîïôöùûüœæ]", re.IGNORECASE)
# Common French tokens that are NOT also everyday English words (so "son"/"ton"/"car"/
# "as"/"on"/"a" are deliberately excluded to avoid flipping English text to French).
_FRENCH_WORDS = frozenset(
    "je tu il elle nous vous ils elles oui non bonjour bonsoir salut merci "
    "avec pour dans sur par le la les un une des du au aux ce cet cette ces "
    "mon mes ma ta tes sa ses notre nos votre vos leur leurs "
    "est sont suis etes etre avez avons ont vais veux voudrais voulez "
    "parlez parle parler pouvez peux comprends comprendre et ou mais donc "
    "que qui quoi quel quelle quels quelles comment combien quand pourquoi "
    "pas ne plus tres trop bien alors aussi maintenant francais "
    "s'il plait c'est d'accord j'ai qu'il aujourd'hui".split()
)
_WORD_RE = re.compile(r"[a-zàâäçéèêëîïôöùûüœæ']+", re.IGNORECASE)


def looks_french(text: str) -> bool:
    """True when ``text`` reads as French (accents, or enough French function words)."""
    if _FRENCH_ACCENTS.search(text):
        return True
    words = _WORD_RE.findall(text.lower())
    if not words:
        return False
    hits = sum(1 for w in words if w in _FRENCH_WORDS)
    # Two markers, or one in a short utterance, is a confident French signal.
    return hits >= 2 or (hits == 1 and len(words) <= 4)
