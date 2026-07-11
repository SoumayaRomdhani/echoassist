"""IngestService.delete_document: remove the file and purge its vectors."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.api.ingest_service import IngestService, UnsupportedDocument
from src.rag.ingest import IngestReport


def _service(tmp_path: Path, deleter=None) -> IngestService:
    return IngestService(
        data_dir=tmp_path,
        indexer=lambda d, dom: IngestReport(documents=1, chunks=1, collection_count=1),
        deleter=deleter,
    )


async def test_delete_removes_file_and_purges_vectors(tmp_path: Path) -> None:
    seen: list[tuple[str, str]] = []
    svc = _service(tmp_path, deleter=lambda domain, source: (seen.append((domain, source)), 4)[1])
    docs = svc.docs_dir("helpdesk")
    docs.mkdir(parents=True)
    (docs / "kb.md").write_text("content", encoding="utf-8")

    report = await svc.delete_document("helpdesk", "kb.md")

    assert report.file_removed is True
    assert report.chunks_removed == 4
    assert not (docs / "kb.md").exists()             # file gone from disk
    assert seen == [("helpdesk", "kb.md")]           # store purged by source


async def test_delete_purges_orphan_vectors_when_file_already_gone(tmp_path: Path) -> None:
    svc = _service(tmp_path, deleter=lambda domain, source: 2)
    report = await svc.delete_document("helpdesk", "gone.md")
    assert report.file_removed is False              # no file on disk...
    assert report.chunks_removed == 2                # ...but orphan vectors still cleaned


async def test_delete_reports_nothing_when_absent(tmp_path: Path) -> None:
    svc = _service(tmp_path, deleter=lambda domain, source: 0)
    report = await svc.delete_document("helpdesk", "nope.md")
    assert report.file_removed is False and report.chunks_removed == 0


async def test_delete_rejects_unsupported_filename(tmp_path: Path) -> None:
    with pytest.raises(UnsupportedDocument):
        await _service(tmp_path).delete_document("helpdesk", "malware.exe")


async def test_delete_preserves_subdirectory_source(tmp_path: Path) -> None:
    """A doc ingested as a/faq.md must be purged and unlinked by its relative source."""
    seen: list[str] = []
    svc = _service(tmp_path, deleter=lambda domain, source: (seen.append(source), 1)[1])
    docs = svc.docs_dir("helpdesk")
    (docs / "a").mkdir(parents=True)
    (docs / "a" / "faq.md").write_text("x", encoding="utf-8")

    report = await svc.delete_document("helpdesk", "a/faq.md")

    assert seen == ["a/faq.md"]                       # purged by relative source, not "faq.md"
    assert report.filename == "a/faq.md"
    assert report.file_removed and not (docs / "a" / "faq.md").exists()


@pytest.mark.parametrize("bad", ["../secret.md", "a/../../etc/passwd.md", "/abs/path.md"])
async def test_delete_rejects_path_traversal(tmp_path: Path, bad: str) -> None:
    with pytest.raises(UnsupportedDocument):
        await _service(tmp_path).delete_document("helpdesk", bad)


async def test_delete_purges_before_unlink_so_a_store_failure_keeps_the_file(
    tmp_path: Path,
) -> None:
    def boom(domain: str, source: str) -> int:
        raise RuntimeError("qdrant is down")

    svc = _service(tmp_path, deleter=boom)
    docs = svc.docs_dir("helpdesk")
    docs.mkdir(parents=True)
    (docs / "kb.md").write_text("x", encoding="utf-8")

    with pytest.raises(RuntimeError):
        await svc.delete_document("helpdesk", "kb.md")
    assert (docs / "kb.md").exists()                  # purge failed first -> file untouched


async def test_reindex_rebuilds_from_disk(tmp_path: Path) -> None:
    calls: list[tuple[Path, str]] = []
    svc = IngestService(
        data_dir=tmp_path,
        indexer=lambda d, dom: IngestReport(1, 1, 1),
        reindexer=lambda docs_dir, domain: (
            calls.append((docs_dir, domain)),
            IngestReport(documents=2, chunks=5, collection_count=5),
        )[1],
    )
    report = await svc.reindex("helpdesk")
    assert report.chunks == 5 and calls[0][1] == "helpdesk"
    assert svc.docs_dir("helpdesk").exists()          # docs dir ensured before reindex


async def test_reindex_requires_configuration(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError):
        await _service(tmp_path).reindex("helpdesk")   # no reindexer wired
