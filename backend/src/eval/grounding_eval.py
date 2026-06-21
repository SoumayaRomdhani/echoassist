"""Grounding-gate calibration (EN/FR).

    python -m src.eval.grounding_eval

Runs a labelled set of on-topic (EN + FR) and off-topic queries through the
retriever and prints, for each: the top reranker score, its confidence, and the
gate decision (ANSWER/REFUSE) vs the expected one. Use this to set
GROUNDING_MIN_CONFIDENCE on evidence — the threshold must ACCEPT legitimate FR
questions and REFUSE out-of-domain ones. Local, no LLM/quota; requires Qdrant
running + the domain ingested.
"""

from __future__ import annotations

from dataclasses import dataclass

from config.settings import build_retriever, get_settings
from src.agent.guardrails import confidence, is_grounded
from src.console import FAIL, OK, bold, dim, init_console
from src.log import setup_logging


@dataclass(frozen=True, slots=True)
class Case:
    query: str
    expect_answer: bool
    label: str


_CASES = [
    Case("What is the salary range for the backend role?", True, "EN on-topic"),
    Case("What are the steps in the interview process?", True, "EN on-topic"),
    Case("Quelle est la fourchette de salaire pour ce poste ?", True, "FR on-topic"),
    Case("Est-ce que je peux télétravailler entièrement ?", True, "FR on-topic"),
    Case("Quelle est la politique de teletravail ?", True, "FR no-accents (STT-like)"),
    Case("What is the weather in Paris today?", False, "off-topic"),
    Case("Can you recommend a good pizza recipe?", False, "off-topic"),
    Case("What is the capital of Australia?", False, "off-topic"),
]


def main() -> None:
    settings = get_settings()
    init_console()
    setup_logging(settings.log_level)
    threshold = settings.grounding_min_confidence
    retriever = build_retriever(settings)

    print(bold(f"\nGrounding calibration — threshold={threshold}\n"))
    passed = 0
    for case in _CASES:
        chunks = retriever.retrieve(case.query)
        top = chunks[0].score if chunks else float("-inf")
        conf = confidence(top) if chunks else 0.0
        answered = bool(chunks) and is_grounded(top, threshold)
        ok = answered == case.expect_answer
        passed += ok
        decision = "ANSWER" if answered else "REFUSE"
        mark = OK if ok else FAIL
        print(f"  {mark} [{case.label:<22}] conf={conf:5.3f} -> {decision:<6}  {dim(case.query)}")

    print(bold(f"\n{passed}/{len(_CASES)} cases match the expected decision "
               f"(want: FR accepted, off-topic refused)\n"))


if __name__ == "__main__":
    main()
