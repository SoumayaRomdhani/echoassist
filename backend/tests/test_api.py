"""REST API: health, domains, the call lifecycle, campaigns, and doc upload.

Drives a real call through the (fake-backed) runner so the GET endpoints assert
against genuinely persisted data, then covers campaigns and document upload.
"""

from __future__ import annotations

import pytest

from tests.conftest import run_call_to_completion

pytestmark = pytest.mark.asyncio


async def test_root_and_health(client) -> None:
    root = await client.get("/")
    assert root.status_code == 200 and root.json()["version"]

    health = await client.get("/health")
    assert health.status_code == 200 and health.json()["status"] == "ok"


async def test_ready_reports_component_health(client) -> None:
    body = (await client.get("/ready")).json()
    # Database is in-memory SQLite (always ok); Qdrant is probed too (env-dependent),
    # so assert on the components map rather than the aggregate status.
    assert body["components"]["database"] == "ok"
    assert "qdrant" in body["components"]
    assert body["status"] in ("ok", "degraded")


async def test_list_and_get_domains(client) -> None:
    domains = (await client.get("/domains")).json()
    names = {d["name"] for d in domains}
    assert "screening" in names

    screening = (await client.get("/domains/screening")).json()
    assert screening["question_count"] == 5
    assert "years_experience" in screening["slots"]
    assert screening["indexed"] is None        # best-effort; no pool in tests

    assert (await client.get("/domains/does-not-exist")).status_code == 404


async def test_call_lifecycle_persists_and_is_served(client, resources) -> None:
    session = await run_call_to_completion(resources)
    call_id = session.call_id
    assert session.status == "completed" and session.consent_granted is True

    listing = (await client.get("/calls")).json()
    assert listing["total"] == 1
    assert listing["items"][0]["call_id"] == call_id
    assert listing["items"][0]["has_notes"] is True

    detail = (await client.get(f"/calls/{call_id}")).json()
    assert detail["status"] == "completed"
    assert detail["campaign_name"]
    assert any(turn["role"] == "assistant" for turn in detail["transcript"])
    assert detail["notes"]["years_experience"] == "6 years"
    assert "six years" in detail["summary"]

    notes = (await client.get(f"/calls/{call_id}/notes")).json()
    assert notes["notes"]["overall_fit"] == "strong"

    summary = (await client.get(f"/calls/{call_id}/summary")).json()
    assert summary["summary"] == detail["summary"]

    consent = (await client.get(f"/calls/{call_id}/consent")).json()
    assert [c["decision"] for c in consent] == ["accepted"]
    assert consent[0]["granted"] is True
    assert len(consent[0]["disclosure_hash"]) == 64   # sha256 of the spoken disclosure


async def test_declined_call_is_recorded_without_notes(client, resources) -> None:
    session = await run_call_to_completion(resources, consent=False)
    call_id = session.call_id
    assert session.status == "declined"

    detail = (await client.get(f"/calls/{call_id}")).json()
    assert detail["status"] == "declined"
    assert detail["consent_granted"] is False
    assert detail["notes"] is None

    assert (await client.get(f"/calls/{call_id}/notes")).status_code == 404

    consent = (await client.get(f"/calls/{call_id}/consent")).json()
    assert consent[0]["decision"] == "refused" and consent[0]["granted"] is False


async def test_start_call_endpoint_returns_202_with_ws_url(client) -> None:
    response = await client.post("/calls", json={"consent": True})
    assert response.status_code == 202
    body = response.json()
    assert body["ws_url"] == f"/ws/calls/{body['call_id']}"


async def test_default_engine_consent_clip_selection() -> None:
    # The production engine must honor the consent flag: a refusal plays the "no" clip,
    # so a server-started call can actually reach the declined path.
    from src.api.context import DefaultCallEngine, ProviderPool
    from tests.conftest import make_settings

    settings = make_settings()
    engine = DefaultCallEngine(settings, ProviderPool(settings))
    assert engine._consent_clip(consent=True).name == "sample_consent.wav"
    assert engine._consent_clip(consent=False).name == "sample_decline.wav"


async def test_start_call_503_when_voice_models_missing(sqlite_engine) -> None:
    # Light (data-only) image: POST /calls must fail fast with a clear 503.
    from httpx import ASGITransport, AsyncClient

    from src.api.app import create_app
    from tests.conftest import make_resources

    resources = make_resources(sqlite_engine, preflight_error="voice models not installed")
    transport = ASGITransport(app=create_app(resources))
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as http:
            response = await http.post("/calls", json={"consent": True})
        assert response.status_code == 503
        assert "voice models" in response.json()["detail"]
    finally:
        await resources.call_manager.aclose()


async def test_call_status_falls_back_to_persisted_record(client, resources) -> None:
    session = await run_call_to_completion(resources)
    status = (await client.get(f"/calls/{session.call_id}/status")).json()
    assert status["status"] == "completed"
    assert status["domain"] == "screening"


async def test_unknown_call_returns_404(client) -> None:
    for suffix in ("", "/notes", "/summary"):
        assert (await client.get(f"/calls/missing{suffix}")).status_code == 404


async def test_campaign_endpoints(client, resources) -> None:
    await run_call_to_completion(resources)   # creates the default campaign

    campaigns = (await client.get("/campaigns")).json()
    assert len(campaigns) == 1
    campaign_id = campaigns[0]["id"]

    created = await client.post(
        "/campaigns", json={"name": "Backend hiring", "domain": "screening"}
    )
    assert created.status_code == 201 and created.json()["name"] == "Backend hiring"

    one = (await client.get(f"/campaigns/{campaign_id}")).json()
    assert one["id"] == campaign_id

    calls = (await client.get(f"/campaigns/{campaign_id}/calls")).json()
    assert calls["total"] == 1

    assert (await client.get("/campaigns/99999")).status_code == 404


async def test_document_upload_triggers_ingest(client) -> None:
    files = {"file": ("benefits.md", b"# Benefits\nUnlimited coffee.", "text/markdown")}
    response = await client.post("/domains/screening/documents", files=files)
    assert response.status_code == 201
    body = response.json()
    assert body["filename"] == "benefits.md"
    assert body["chunks"] == 1


async def test_document_upload_rejects_unsupported_type(client) -> None:
    files = {"file": ("malware.exe", b"MZ", "application/octet-stream")}
    response = await client.post("/domains/screening/documents", files=files)
    assert response.status_code == 400


async def test_document_upload_unknown_domain_404(client) -> None:
    files = {"file": ("kb.md", b"hello", "text/markdown")}
    assert (await client.post("/domains/nope/documents", files=files)).status_code == 404
