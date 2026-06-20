"""Retrieval quality evaluation: Recall@K and nDCG@K over a gold set.

    python -m src.eval.retrieval_eval [--k 6]

Requires Qdrant running and the domain ingested (scripts/ingest_docs.py).
Relevance is judged at the document level: a retrieved chunk counts for its
source document.
"""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from pathlib import Path

import yaml

from config.settings import build_retriever, get_settings
from src.console import bold, dim, init_console
from src.log import setup_logging
from src.rag.retriever import Retriever


@dataclass(frozen=True, slots=True)
class GoldQuery:
    query: str
    relevant: set[str]


@dataclass(frozen=True, slots=True)
class QueryScore:
    query: str
    recall: float
    ndcg: float
    ranked_sources: list[str]


def load_gold_set(path: Path) -> list[GoldQuery]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [GoldQuery(q["query"], set(q["relevant"])) for q in data["queries"]]


def _ranked_sources(retriever: Retriever, query: str, k: int) -> list[str]:
    ordered: list[str] = []
    for chunk in retriever.retrieve(query):
        if chunk.chunk.source not in ordered:
            ordered.append(chunk.chunk.source)
    return ordered[:k]


def _ndcg(ranked: list[str], relevant: set[str], k: int) -> float:
    dcg = sum(1.0 / math.log2(i + 2) for i, s in enumerate(ranked[:k]) if s in relevant)
    ideal_hits = min(len(relevant), k)
    idcg = sum(1.0 / math.log2(i + 2) for i in range(ideal_hits))
    return dcg / idcg if idcg else 0.0


def evaluate(retriever: Retriever, gold: list[GoldQuery], k: int) -> list[QueryScore]:
    scores: list[QueryScore] = []
    for item in gold:
        ranked = _ranked_sources(retriever, item.query, k)
        found = {s for s in ranked if s in item.relevant}
        recall = len(found) / len(item.relevant) if item.relevant else 0.0
        scores.append(QueryScore(item.query, recall, _ndcg(ranked, item.relevant, k), ranked))
    return scores


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate retrieval (Recall@K, nDCG@K).")
    parser.add_argument("--k", type=int, default=None, help="Cutoff K (default: RAG_TOP_K).")
    args = parser.parse_args()

    settings = get_settings()
    init_console()
    setup_logging(settings.log_level)
    k = args.k or settings.rag_top_k

    gold = load_gold_set(settings.data_dir / "eval" / f"{settings.domain}.yaml")
    retriever = build_retriever(settings)
    scores = evaluate(retriever, gold, k)

    print(bold(f"\nRetrieval eval — domain={settings.domain}  K={k}  ({len(scores)} queries)\n"))
    for s in scores:
        mark = "✓" if s.recall > 0 else "✗"
        print(f"  {mark} R={s.recall:.2f} nDCG={s.ndcg:.2f}  {s.query}")
        print(dim(f"      -> {', '.join(s.ranked_sources) or '(none)'}"))

    mean_recall = sum(s.recall for s in scores) / len(scores)
    mean_ndcg = sum(s.ndcg for s in scores) / len(scores)
    print(bold(f"\nmean Recall@{k}={mean_recall:.3f}   mean nDCG@{k}={mean_ndcg:.3f}\n"))


if __name__ == "__main__":
    main()
