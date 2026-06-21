"""Notes extraction accuracy vs ground truth.

    python -m src.eval.notes_eval

Runs NotesExtractor on each synthetic dialogue (data/eval/dialogues.json) with
empty slots — so the factual fields are extracted purely from the transcript —
and checks each against acceptable ground-truth substrings. Needs the LLM
(Gemini) available; create dialogues first with scripts/gen_test_dialogues.py.
"""

from __future__ import annotations

import asyncio
import json

from config.settings import build_llm, get_settings
from src.agent.notes import NotesExtractor, load_notes_schema
from src.agent.state import ConversationState
from src.console import bold, dim, init_console
from src.log import setup_logging
from src.providers.errors import ProviderError


def _matches(actual: str, accepted: list[str]) -> bool:
    text = (actual or "").lower()
    return any(sub.lower() in text for sub in accepted)


async def main() -> None:
    settings = get_settings()
    init_console()
    setup_logging(settings.log_level)

    dialogues_path = settings.data_dir / "eval" / "dialogues.json"
    if not dialogues_path.exists():
        raise SystemExit("No dialogues.json — run: python scripts/gen_test_dialogues.py")
    dialogues = json.loads(dialogues_path.read_text(encoding="utf-8"))

    schema = load_notes_schema(settings.domain, settings.config_dir)
    extractor = NotesExtractor(build_llm(settings), schema)

    field_hits: dict[str, int] = {}
    field_total: dict[str, int] = {}
    print(bold(f"\nNotes eval — {len(dialogues)} dialogues\n"))

    for dialogue in dialogues:
        state = ConversationState(call_id=dialogue["call_id"], transcript=dialogue["transcript"])
        notes = await extractor.extract(state)
        print(bold(dialogue["call_id"]))
        for field, accepted in dialogue["expected_notes"].items():
            ok = _matches(str(notes.get(field, "")), accepted)
            field_hits[field] = field_hits.get(field, 0) + int(ok)
            field_total[field] = field_total.get(field, 0) + 1
            mark = "✓" if ok else "✗"
            expected = dim("expected~ " + "/".join(accepted))
            print(f"  {mark} {field}: {notes.get(field, '')!r}  {expected}")

    total_hits = sum(field_hits.values())
    total = sum(field_total.values())
    print(bold("\nper-field accuracy"))
    for field in field_total:
        print(f"  {field}: {field_hits[field]}/{field_total[field]}")
    print(bold(f"\noverall notes accuracy = {total_hits}/{total} = {total_hits / total:.3f}\n"))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except ProviderError as exc:
        from src.console import FAIL

        raise SystemExit(f"{FAIL} {exc}") from exc
