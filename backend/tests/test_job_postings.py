"""Job-posting API: generate, list, get, curate — model-free (fake LLM, SQLite)."""

from __future__ import annotations

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


@pytest.mark.asyncio
async def test_generation_unavailable_without_llm_is_503(sqlite_engine) -> None:
    client = await _client(sqlite_engine, llm_factory=None)
    async with client:
        resp = await client.post(
            "/job-postings", json={"title": "SRE", "description": "K8s."}
        )
    assert resp.status_code == 503
