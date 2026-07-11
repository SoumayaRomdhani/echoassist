"""Document upload — adds a file to a domain's KB and triggers RAG re-ingest."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from src.agent.domain import list_available_domains
from src.api.context import AppResources, get_resources
from src.api.ingest_service import DocumentTooLarge, UnsupportedDocument
from src.api.schemas import DocumentUploadOut

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
    )
