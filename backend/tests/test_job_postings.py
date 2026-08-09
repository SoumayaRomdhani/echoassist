"""Job-posting API: generate, list, get, curate — model-free (fake LLM, SQLite)."""

from __future__ import annotations

import asyncio
import time

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.api.app import create_app
from src.providers.llm.base import LLMProvider
from src.providers.types import LLMResponse, ToolCall
from tests.conftest import make_resources


class QuestionsLLM(LLMProvider):
    """Fake LLM that drafts two questions via a tool call (no network)."""

    async def chat(self, messages, tools=None) -> LLMResponse:
        args = {"questions": [
            {"text": "How many years with Kubernetes?", "slot": "years_k8s"},
            {"text": "Are you open to on-call?"},
        ]}
        return LLMResponse(text="", tool_calls=[ToolCall("q", "record_questions", args)])


async def _client(engine, *, llm_factory=lambda: QuestionsLLM()) -> AsyncClient:
    resources = make_resources(engine, llm_factory=llm_factory)
    transport = ASGITransport(app=create_app(resources))
    return AsyncClient(transport=transport, base_url="http://test")


@pytest_asyncio.fixture
async def jp_client(sqlite_engine):
    client = await _client(sqlite_engine)
    async with client:
        yield client


@pytest.mark.asyncio
async def test_create_generates_and_persists_questions(jp_client) -> None:
    resp = await jp_client.post(
        "/job-postings",
        json={"title": "SRE", "description": "We run K8s at scale; on-call rotation."},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "draft"
    assert body["domain"] == "screening"
    slots = [q["slot"] for q in body["questions"]]
    assert slots == ["years_k8s", "are_you_open_to_on_call"]
    assert all(q["enabled"] for q in body["questions"])
    assert body["questions"][0]["id"] == "q1"


@pytest.mark.asyncio
async def test_list_and_get(jp_client) -> None:
    created = (await jp_client.post(
        "/job-postings", json={"title": "SRE", "description": "K8s."}
    )).json()

    listed = (await jp_client.get("/job-postings")).json()
    assert [p["id"] for p in listed] == [created["id"]]

    got = await jp_client.get(f"/job-postings/{created['id']}")
    assert got.status_code == 200
    assert got.json()["title"] == "SRE"


@pytest.mark.asyncio
async def test_patch_curates_and_confirms(jp_client) -> None:
    created = (await jp_client.post(
        "/job-postings", json={"title": "SRE", "description": "K8s."}
    )).json()
    job_id = created["id"]

    # Recruiter disables one, edits one, adds a new one, and confirms.
    edited = {
        "status": "confirmed",
        "questions": [
            {"text": "How many years with Kubernetes?", "slot": "years_k8s", "enabled": False},
            {"text": "Comfortable owning production incidents?", "slot": "prod_ownership"},
            {"text": "Preferred cloud provider?"},  # new, no id/slot -> server assigns
        ],
    }
    resp = await jp_client.patch(f"/job-postings/{job_id}", json=edited)
    assert resp.status_code == 200
    body = resp.json()

    assert body["status"] == "confirmed"
    assert [q["slot"] for q in body["questions"]] == [
        "years_k8s", "prod_ownership", "preferred_cloud_provider"
    ]
    assert body["questions"][0]["enabled"] is False   # disable preserved
    assert [q["id"] for q in body["questions"]] == ["q1", "q2", "q3"]  # re-ided


@pytest.mark.asyncio
async def test_missing_posting_is_404(jp_client) -> None:
    assert (await jp_client.get("/job-postings/999")).status_code == 404
    assert (await jp_client.patch("/job-postings/999", json={"title": "x"})).status_code == 404
    assert (await jp_client.delete("/job-postings/999")).status_code == 404


@pytest.mark.asyncio
async def test_delete_removes_the_posting(jp_client) -> None:
    created = (await jp_client.post(
        "/job-postings", json={"title": "SRE", "description": "K8s."}
    )).json()

    resp = await jp_client.delete(f"/job-postings/{created['id']}")
    assert resp.status_code == 204
    assert (await jp_client.get(f"/job-postings/{created['id']}")).status_code == 404
    assert (await jp_client.get("/job-postings")).json() == []


@pytest.mark.asyncio
async def test_generation_unavailable_without_llm_is_503(sqlite_engine) -> None:
    client = await _client(sqlite_engine, llm_factory=None)
    async with client:
        resp = await client.post(
            "/job-postings", json={"title": "SRE", "description": "K8s."}
        )
    assert resp.status_code == 503


# --------------------------------------------------------------------------- #
# POST /calls with job_posting_id -> tailored interview                       #
# --------------------------------------------------------------------------- #
async def _wait_ended(call_manager, call_id: str, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while call_manager.get(call_id).ended_at is None:
        await asyncio.sleep(0.01)
        if time.monotonic() > deadline:
            raise TimeoutError(f"call {call_id} did not finish in {timeout}s")


@pytest.mark.asyncio
async def test_call_runs_the_tailored_interview_from_a_confirmed_posting(sqlite_engine) -> None:
    resources = make_resources(sqlite_engine, llm_factory=lambda: QuestionsLLM())
    transport = ASGITransport(app=create_app(resources))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = (await client.post(
            "/job-postings", json={"title": "SRE", "description": "K8s."}
        )).json()
        await client.patch(f"/job-postings/{created['id']}", json={"status": "confirmed"})

        resp = await client.post("/calls", json={"job_posting_id": created["id"], "consent": True})
        assert resp.status_code == 202
        call_id = resp.json()["call_id"]

        await _wait_ended(resources.call_manager, call_id)
        detail = (await client.get(f"/calls/{call_id}")).json()

    await resources.call_manager.aclose()

    # The agent asked the tailored question (from the job posting), not the static YAML one.
    texts = " ".join(t["text"] for t in detail["transcript"])
    assert "How many years with Kubernetes?" in texts
    assert detail["status"] == "completed"


@pytest.mark.asyncio
async def test_call_rejects_unconfirmed_posting(jp_client) -> None:
    created = (await jp_client.post(
        "/job-postings", json={"title": "SRE", "description": "K8s."}
    )).json()
    resp = await jp_client.post("/calls", json={"job_posting_id": created["id"]})
    assert resp.status_code == 409   # still a draft


@pytest.mark.asyncio
async def test_call_rejects_unknown_posting(jp_client) -> None:
    resp = await jp_client.post("/calls", json={"job_posting_id": 999})
    assert resp.status_code == 404
