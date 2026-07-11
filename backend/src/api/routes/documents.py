"""Document endpoints — add/remove a file in a domain's KB and re-index RAG."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from src.agent.domain import list_available_domains
from src.api.context import AppResources, get_resources
from src.api.ingest_service import DocumentTooLarge, UnsupportedDocument
from src.api.schemas import (
    DocumentDeleteOut,
    DocumentUploadOut,
    DomainReindexOut,
    SkippedDocumentOut,
)

log = logging.getLogger("echoassist.api.documents")

router = APIRouter(prefix="/domains", tags=["documents"])


@router.post("/{domain}/documents", response_model=DocumentUploadOut, status_code=201)
async def upload_document(
    domain: str,
    file: UploadFile = File(...),
    resources: AppResources = Depends(get_resources),
) -> DocumentUploadOut:
    """Store an uploaded knowledge-base document and re-index the domain collection.

    Accepts Markdown, plain text, PDF, Word (.docx), and HTML (see
    ``rag.loaders.SUPPORTED_SUFFIXES``); unsupported types are rejected with 400.
    """
    if domain not in list_available_domains(resources.settings.config_dir):
        raise HTTPException(status_code=404, detail=f"domain '{domain}' not found")

    try:
        content = await resources.ingest_service.read_capped(file)
    except DocumentTooLarge as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc

    try:
        report = await resources.ingest_service.add_document(
            domain, file.filename or "document.md", content
        )
    except UnsupportedDocument as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - ingest needs Qdrant; surface as 503, not 500
        log.warning("ingest failed for domain %s: %s", domain, exc)
        raise HTTPException(
            status_code=503, detail=f"ingest failed (is Qdrant running?): {exc}"
        ) from exc

    return DocumentUploadOut(
        domain=domain,
        filename=(file.filename or "document.md"),
        documents=report.documents,
        chunks=report.chunks,
        collection_count=report.collection_count,
        skipped=[SkippedDocumentOut(source=s.source, reason=s.reason) for s in report.skipped],
    )


@router.delete("/{domain}/documents/{source:path}", response_model=DocumentDeleteOut)
async def delete_document(
    domain: str,
    source: str,
    resources: AppResources = Depends(get_resources),
) -> DocumentDeleteOut:
    """Remove a document from a domain: purge its vectors and delete its file.

    ``source`` may be a relative path (``a/faq.md``) — the ``:path`` converter captures
    the slashes. Returns 404 if neither a file nor any indexed chunks exist (so it also
    cleans orphaned vectors left by a file deleted outside the app).
    """
    if domain not in list_available_domains(resources.settings.config_dir):
        raise HTTPException(status_code=404, detail=f"domain '{domain}' not found")

    try:
        report = await resources.ingest_service.delete_document(domain, source)
    except UnsupportedDocument as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - purge needs Qdrant; surface as 503, not 500
        log.warning("delete failed for domain %s: %s", domain, exc)
        raise HTTPException(
            status_code=503, detail=f"delete failed (is Qdrant running?): {exc}"
        ) from exc

    if not report.file_removed and report.chunks_removed == 0:
        raise HTTPException(
            status_code=404, detail=f"document '{source}' not found in domain '{domain}'"
        )

    return DocumentDeleteOut(
        domain=domain,
        filename=report.filename,
        file_removed=report.file_removed,
        chunks_removed=report.chunks_removed,
    )


@router.post("/{domain}/reindex", response_model=DomainReindexOut)
async def reindex_domain(
    domain: str,
    resources: AppResources = Depends(get_resources),
) -> DomainReindexOut:
    """Rebuild a domain's collection from the files currently on disk (clean rebuild)."""
    if domain not in list_available_domains(resources.settings.config_dir):
        raise HTTPException(status_code=404, detail=f"domain '{domain}' not found")

    try:
        report = await resources.ingest_service.reindex(domain)
    except Exception as exc:  # noqa: BLE001 - reindex needs Qdrant; surface as 503, not 500
        log.warning("reindex failed for domain %s: %s", domain, exc)
        raise HTTPException(
            status_code=503, detail=f"reindex failed (is Qdrant running?): {exc}"
        ) from exc

    return DomainReindexOut(
        domain=domain,
        documents=report.documents,
        chunks=report.chunks,
        collection_count=report.collection_count,
        skipped=[SkippedDocumentOut(source=s.source, reason=s.reason) for s in report.skipped],
    )
