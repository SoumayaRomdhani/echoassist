"""Rich citations: page/heading provenance grouped from the cited retrieved chunks."""

from __future__ import annotations

from src.agent.grounding import Citation, build_citations
from src.rag.types import Chunk, ScoredChunk


def _scored(source: str, *, score: float, ordinal: int = 0, **meta) -> ScoredChunk:
    chunk = Chunk(id=f"{source}#{ordinal}", source=source, text="t", ordinal=ordinal, metadata=meta)
    return ScoredChunk(chunk=chunk, score=score)


def test_label_formats_source_heading_and_pages() -> None:
    assert Citation("guide.pdf").label() == "guide.pdf"
    assert Citation("guide.pdf", pages=[17]).label() == "guide.pdf (p17)"
    assert (
        Citation("guide.pdf", pages=[17, 18], heading="Managing factors").label()
        == "guide.pdf — Managing factors (p17, p18)"
    )


def test_build_citations_only_includes_cited_sources() -> None:
    retrieved = [
        _scored("a.pdf", score=0.9, page=1),
        _scored("b.pdf", score=0.8, page=2),
    ]
    # Only a.pdf is cited in the answer text.
    cites = build_citations("See [a.pdf] for details.", retrieved)
    assert [c.source for c in cites] == ["a.pdf"]
    assert cites[0].pages == [1]


def test_build_citations_aggregates_pages_and_picks_best_heading() -> None:
    retrieved = [
        _scored("guide.pdf", score=0.4, ordinal=0, page=18, heading="Overview"),
        _scored("guide.pdf", score=0.9, ordinal=1, page=17, heading="Managing factors"),
        _scored("guide.pdf", score=0.7, ordinal=2, page=17, heading="Managing factors"),
    ]
    [cite] = build_citations("As in [guide.pdf].", retrieved)
    assert cite.pages == [17, 18]                         # distinct, ascending
    assert cite.heading == "Managing factors"             # from the highest-scoring chunk
    assert cite.score == 0.9                              # best score
    assert cite.chunk_ids[0] == "guide.pdf#1"             # ranked best-first
    assert cite.label() == "guide.pdf — Managing factors (p17, p18)"


def test_build_citations_handles_chunks_without_page_or_heading() -> None:
    # A plain .md chunk (no page/heading) still yields a bare-source citation.
    [cite] = build_citations("[faq.md]", [_scored("faq.md", score=0.5)])
    assert cite.pages == [] and cite.heading == ""
    assert cite.label() == "faq.md"
    assert cite.to_dict() == {"source": "faq.md", "label": "faq.md", "score": 0.5}
