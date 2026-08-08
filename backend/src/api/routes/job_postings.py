"""Job-posting endpoints: draft JD-based interview questions, then curate them.

``POST`` generates questions from a job description via the LLM; the recruiter then
reviews (``GET``) and edits/confirms (``PATCH``). The confirmed set later drives a
tailored interview instead of the static ``screening.yaml`` flow.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from src.agent.question_gen import MAX_QUESTIONS_LIMIT, QuestionGenerator, normalize_questions
from src.api.context import AppResources, get_resources
from src.api.schemas import JobPostingCreate, JobPostingOut, JobPostingUpdate
from src.storage import queries

router = APIRouter(prefix="/job-postings", tags=["job-postings"])


def _generator(resources: AppResources) -> QuestionGenerator:
    if resources.llm_factory is None:
        raise HTTPException(
            status_code=503, detail="LLM is not configured for question generation"
        )
    return QuestionGenerator(resources.llm_factory())


@router.post("", response_model=JobPostingOut, status_code=201)
async def create_job_posting(
    body: JobPostingCreate, resources: AppResources = Depends(get_resources)
) -> JobPostingOut:
    questions = await _generator(resources).generate(
        body.description, max_questions=body.max_questions
    )
    async with resources.sessionmaker() as db:
        posting = await queries.create_job_posting(
            db, title=body.title, domain=body.domain,
            description=body.description, questions=questions,
        )
    return JobPostingOut.from_orm_model(posting)


@router.get("", response_model=list[JobPostingOut])
async def list_job_postings(
    resources: AppResources = Depends(get_resources),
) -> list[JobPostingOut]:
    async with resources.sessionmaker() as db:
        postings = await queries.list_job_postings(db)
    return [JobPostingOut.from_orm_model(p) for p in postings]


@router.get("/{job_id}", response_model=JobPostingOut)
async def get_job_posting(
    job_id: int, resources: AppResources = Depends(get_resources)
) -> JobPostingOut:
    async with resources.sessionmaker() as db:
        posting = await queries.get_job_posting(db, job_id)
    if posting is None:
        raise HTTPException(status_code=404, detail=f"job posting {job_id} not found")
    return JobPostingOut.from_orm_model(posting)


@router.patch("/{job_id}", response_model=JobPostingOut)
async def update_job_posting(
    job_id: int, body: JobPostingUpdate, resources: AppResources = Depends(get_resources)
) -> JobPostingOut:
    # Re-normalize the curated set: re-id, unique slots, preserve enabled, generous cap.
    questions = None
    if body.questions is not None:
        questions = normalize_questions(
            [q.model_dump() for q in body.questions], max_questions=MAX_QUESTIONS_LIMIT
        )
    async with resources.sessionmaker() as db:
        posting = await queries.update_job_posting(
            db, job_id, title=body.title, questions=questions, status=body.status
        )
    if posting is None:
        raise HTTPException(status_code=404, detail=f"job posting {job_id} not found")
    return JobPostingOut.from_orm_model(posting)
