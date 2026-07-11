"""Upload size cap: read_capped rejects oversized files without buffering them."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.api.ingest_service import DocumentTooLarge, IngestService
from src.rag.ingest import IngestReport


class FakeUpload:
    """Minimal stand-in for Starlette's UploadFile: async read(size) + optional .size."""

    def __init__(self, data: bytes, *, size: int | None = None) -> None:
        self._data = data
        self._pos = 0
        self.size = size

    async def read(self, n: int = -1) -> bytes:
        n = len(self._data) - self._pos if n is None or n < 0 else n
        piece = self._data[self._pos : self._pos + n]
        self._pos += len(piece)
        return piece


def _service(limit: int, tmp_path: Path) -> IngestService:
    return IngestService(
        data_dir=tmp_path,
        indexer=lambda d, dom: IngestReport(documents=1, chunks=1, collection_count=1),
        max_upload_bytes=limit,
    )


async def test_read_capped_accepts_within_limit(tmp_path: Path) -> None:
    data = b"x" * 50
    assert await _service(100, tmp_path).read_capped(FakeUpload(data)) == data


async def test_read_capped_allows_exactly_the_limit(tmp_path: Path) -> None:
    data = b"z" * 100
    assert await _service(100, tmp_path).read_capped(FakeUpload(data)) == data


async def test_read_capped_rejects_over_limit_while_streaming(tmp_path: Path) -> None:
    # No size hint -> the cap is enforced from the running byte total.
    with pytest.raises(DocumentTooLarge):
        await _service(100, tmp_path).read_capped(FakeUpload(b"y" * 500))


async def test_read_capped_fast_rejects_using_size_hint(tmp_path: Path) -> None:
    # The parser's size hint rejects before any bytes are read.
    with pytest.raises(DocumentTooLarge):
        await _service(100, tmp_path).read_capped(FakeUpload(b"", size=999))
