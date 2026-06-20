"""Ask the agent a domain question; it retrieves and answers with citations.

This is the Sprint 2 Definition of Done (text in -> grounded, cited answer out):

    python scripts/ask.py "What is the salary range for the backend role?"

Requires Qdrant running and the domain ingested (scripts/ingest_docs.py).
"""

from __future__ import annotations

import argparse
import asyncio

from config.settings import build_llm, build_retriever, get_settings
from src.agent.domain import load_domain_config
from src.agent.grounding import GroundedResponder
from src.console import bold, dim, init_console
from src.log import setup_logging


async def main() -> None:
    parser = argparse.ArgumentParser(description="Ask the agent a grounded, cited question.")
    parser.add_argument("question", help="The question to ask.")
    args = parser.parse_args()

    settings = get_settings()
    init_console()
    setup_logging(settings.log_level)

    domain = load_domain_config(settings.domain, settings.config_dir)
    responder = GroundedResponder(
        build_llm(settings),
        build_retriever(settings),
        system_prompt=domain.system_prompt,
    )

    print(f"\n{bold('QUESTION:')} {args.question}")
    answer = await responder.answer(args.question)

    print(f"\n{bold('ANSWER:')} {answer.text}")
    print(dim(f"\ncitations: {', '.join(answer.citations) or '(none)'}"))
    sources = ", ".join(sorted({c.chunk.source for c in answer.retrieved})) or "(none)"
    print(dim(f"retrieved from: {sources}  ({answer.tool_calls} tool call(s))"))


if __name__ == "__main__":
    asyncio.run(main())
