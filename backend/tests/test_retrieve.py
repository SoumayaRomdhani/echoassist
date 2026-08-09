"""The full-text retrieval endpoint + the mic's RemoteRetriever client.

`POST /domains/{domain}/retrieve` returns each grounded chunk's COMPLETE text (unlike the
dashboard's 300-char `/search` preview), so the microphone can reuse the API's warm RAG
stack instead of loading its own models. `RemoteRetriever` is the client that reconstructs
`ScoredChunk`s from that response and degrades gracefully when the API is unreachable.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

from src.rag.remote import RemoteRetriever
from src.rag.types import Chunk, ScoredChunk


# --- API endpoint ---------------------------------------------------------- #
def _fake_hit(text: str) -> ScoredChunk:
    return ScoredChunk(
        chunk=Chunk(
            id="c1", source="kb.md", text=text, ordinal=3,
            metadata={"page": 2, "heading": "Remote work"},
        ),
        score=0.87,
        components={"rrf": 0.1, "rerank": 0.87},
    )


async def test_retrieve_returns_full_chunk_text_not_the_preview(client, resources) -> None:
    long_text = "remote " * 200  # ~1400 chars — far past the /search 300-char cap
    resources.ingest_service._searcher = lambda domain, query, limit: [_fake_hit(long_text)]

    resp = await client.post("/domains/screening/retrieve", json={"query": "is it remote?"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["domain"] == "screening"
    row = body["results"][0]
    # The whole point: the FULL text survives, so grounding is identical to a local retriever.
    assert row["text"] == long_text
    assert row["metadata"] == {"page": 2, "heading": "Remote work"}
    assert row["score"] == 0.87
    assert (row["id"], row["source"], row["ordinal"]) == ("c1", "kb.md", 3)


async def test_retrieve_rejects_empty_query(client) -> None:
    resp = await client.post("/domains/screening/retrieve", json={"query": "  "})
    assert resp.status_code == 400


async def test_retrieve_unknown_domain_404(client) -> None:
    assert (await client.post("/domains/nope/retrieve", json={"query": "x"})).status_code == 404


# --- RemoteRetriever client ------------------------------------------------ #
class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def read(self, *_: object) -> bytes:
        return self._payload


def test_remote_retriever_reconstructs_scored_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}
    payload = json.dumps(
        {
            "domain": "helpdesk",
            "query": "printer",
            "results": [
                {
                    "id": "c9", "source": "it/faq.md", "text": "Restart the print spooler.",
                    "ordinal": 7, "metadata": {"page": 1, "heading": "Printing"},
                    "score": 0.91, "components": {"rrf": 0.2, "rerank": 0.91},
                }
            ],
        }
    ).encode()

    def _fake_urlopen(request, timeout=None):  # noqa: ANN001 - test stub
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data)
        return _FakeResponse(payload)

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)

    retriever = RemoteRetriever("http://localhost:8000/", "helpdesk")
    chunks = retriever.retrieve("printer")

    assert captured["url"] == "http://localhost:8000/domains/helpdesk/retrieve"
    assert captured["body"]["query"] == "printer"
    assert len(chunks) == 1
    sc = chunks[0]
    assert isinstance(sc, ScoredChunk) and isinstance(sc.chunk, Chunk)
    assert sc.chunk.text == "Restart the print spooler."
    assert sc.chunk.source == "it/faq.md"
    assert sc.chunk.metadata == {"page": 1, "heading": "Printing"}
    assert sc.score == 0.91


def test_remote_retriever_degrades_to_empty_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(request, timeout=None):  # noqa: ANN001 - test stub
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", _boom)

    # A live turn must never crash because the API is down — it grounds on nothing instead.
    assert RemoteRetriever("http://localhost:8000", "helpdesk").retrieve("printer") == []
