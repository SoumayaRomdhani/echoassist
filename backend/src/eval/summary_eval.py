"""Summary fact-coverage eval (a light proxy for faithfulness).

    python -m src.eval.summary_eval

For each reference dialogue, generates the post-call summary and checks how many
ground-truth facts (the same accepted substrings used by notes_eval) appear in
it. This is coverage of expected facts — NOT full faithfulness (hallucination
detection), which needs an LLM judge and is planned for the Sprint 7 benchmark.
Needs the LLM (Gemini); create dialogues with scripts/gen_test_dialogues.py.
"""

from __future__ import annotations

import asyncio
import json

from config.settings import build_llm, get_settings
from src.agent.state import ConversationState
from src.agent.summary import SummaryGenerator
from src.console import FAIL, bold, dim, init_console
from src.log import setup_logging
from src.providers.errors import ProviderError


def _covered(summary: str, accepted: list[str]) -> bool:
    text = summary.lower()
    return any(sub.lower() in text for sub in accepted)


async def main() -> None:
    settings = get_settings()
    init_console()
    setup_logging(settings.log_level)

    dialogues_path = settings.data_dir / "eval" / "dialogues.json"
    if not dialogues_path.exists():
        raise SystemExit("No dialogues.json — run: python scripts/gen_test_dialogues.py")
    dialogues = json.loads(dialogues_path.read_text(encoding="utf-8"))

    summarizer = SummaryGenerator(build_llm(settings))
    total_covered = 0
    total_facts = 0
    print(bold(f"\nSummary fact-coverage — {len(dialogues)} dialogues\n"))

    for dialogue in dialogues:
        state = ConversationState(call_id=dialogue["call_id"], transcript=dialogue["transcript"])
        summary = await summarizer.summarize(state)
        facts = dialogue["expected_notes"]
        covered = sum(_covered(summary, accepted) for accepted in facts.values())
        total_covered += covered
        total_facts += len(facts)
        print(f"{bold(dialogue['call_id'])}  {covered}/{len(facts)} facts")
        print(dim(f"  {summary}"))

    score = total_covered / total_facts if total_facts else 0.0
    print(bold(f"\nfact coverage = {total_covered}/{total_facts} = {score:.3f}\n"))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except ProviderError as exc:
        raise SystemExit(f"{FAIL} {exc}") from exc
