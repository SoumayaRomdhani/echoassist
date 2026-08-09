"""A retriever that delegates to a running EchoAssist API instead of loading models.

The RAG stack (FastEmbed embedder + cross-encoder reranker) costs ~30 s to load into a
process, and that cost is paid on *every* fresh ``run_live.py``. The API server, by
contrast, builds the retriever once and keeps it warm across requests
(:class:`~src.api.context.ProviderPool`). This client lets the microphone path reuse that
resident, warm stack over HTTP: it implements the same ``retrieve(query) -> list[ScoredChunk]``
contract the agent depends on (see :class:`~src.rag.retriever.Retriever`), so it drops in
wherever a local retriever would — the mic process then loads no RAG models and starts
instantly, and the post-disclosure model load that used to steal CPU from the first "yes"
disappears.

Standard library only (``urllib``): no new runtime dependency. ``retrieve`` is already called
off the event loop (``asyncio.to_thread`` in :mod:`src.agent.grounding`), so a blocking
request is correct here.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

from src.rag.types import Chunk, ScoredChunk

log = logging.getLogger("echoassist.rag.remote")


class RemoteRetriever:
    """Reuses a warm API RAG stack via ``POST /domains/{domain}/retrieve``.

    Structurally compatible with :class:`~src.rag.retriever.Retriever` (only ``retrieve`` is
    ever called by the grounding layer), so it can be injected wherever a local retriever is
    expected without changing the agent.
    """

    def __init__(
        self, base_url: str, domain: str, *, limit: int = 32, timeout: float = 10.0
    ) -> None:
        self._url = f"{base_url.rstrip('/')}/domains/{domain}/retrieve"
        self._limit = limit
        self._timeout = timeout

    def retrieve(self, query: str) -> list[ScoredChunk]:
        """Fetch the full grounded chunks for ``query`` from the API.

        Best-effort, exactly like the local retriever's own reranker fallback: on any
        transport/HTTP/parse error the turn degrades to *no context* (the agent refuses or
        falls back) rather than crashing a live turn. Never raises.
        """
        payload = json.dumps({"query": query, "limit": self._limit}).encode("utf-8")
        request = urllib.request.Request(
            self._url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                body = json.load(response)
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            log.warning("remote retrieve failed (%s); answering without context.", exc)
            return []

        return [
            ScoredChunk(
                chunk=Chunk(
                    id=r["id"],
                    source=r["source"],
                    text=r["text"],
                    ordinal=r["ordinal"],
                    metadata=r.get("metadata") or {},
                ),
                score=r["score"],
                components=r.get("components") or {},
            )
            for r in body.get("results", [])
        ]
