"""Finalize a test dialogue: extract notes + summary and persist to Postgres.

A quota-light way to demonstrate the Sprint 4 DoD (notes + summary in Postgres)
without running the full audio interview — it uses a synthetic transcript.

    python scripts/gen_test_dialogues.py        # once, to create the dialogues
    python scripts/finalize_call.py             # finalize the first dialogue
    python scripts/finalize_call.py --index 1

Requires Postgres running: docker compose up -d postgres
"""

from __future__ import annotations

import argparse
import asyncio
import json

from config.settings import build_engine, build_llm, get_settings
from src.agent.finalize import finalize_call
from src.agent.notes import load_notes_schema
from src.agent.state import ConversationState
from src.console import FAIL, bold, dim, init_console
from src.log import setup_logging
from src.providers.errors import ProviderError
from src.runtime import use_selector_event_loop
from src.storage.db import init_db, make_sessionmaker


async def main() -> None:
    parser = argparse.ArgumentParser(description="Finalize a test dialogue into Postgres.")
    parser.add_argument("--index", type=int, default=0, help="Dialogue index in dialogues.json.")
    args = parser.parse_args()

    settings = get_settings()
    init_console()
    setup_logging(settings.log_level)

    dialogues_path = settings.data_dir / "eval" / "dialogues.json"
    if not dialogues_path.exists():
        raise SystemExit("No dialogues.json — run: python scripts/gen_test_dialogues.py")
    dialogues = json.loads(dialogues_path.read_text(encoding="utf-8"))
    dialogue = dialogues[args.index]

    state = ConversationState(
        call_id=dialogue["call_id"], consent_granted=True, transcript=dialogue["transcript"]
    )
    llm = build_llm(settings)
    schema = load_notes_schema(settings.domain, settings.config_dir)

    engine = build_engine(settings)
    await init_db(engine)
    try:
        async with make_sessionmaker(engine)() as session:
            final = await finalize_call(
                session, state, llm=llm, schema=schema,
                campaign_name=settings.default_campaign, domain=settings.domain,
                redact=settings.redact_pii,
            )
    finally:
        await engine.dispose()

    print(f"\n{bold('Notes:')}")
    for key, value in final.notes.items():
        print(f"  {key}: {value}")
    print(f"\n{bold('Summary:')} {final.summary}")
    print(dim(f"\npersisted: campaign='{settings.default_campaign}' "
              f"call_id={dialogue['call_id']} db id={final.call.id}"))


if __name__ == "__main__":
    use_selector_event_loop()
    try:
        asyncio.run(main())
    except ProviderError as exc:
        raise SystemExit(f"{FAIL} {exc}") from exc
