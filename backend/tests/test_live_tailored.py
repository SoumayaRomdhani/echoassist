"""The live mic/LiveKit path builds a tailored interview from a job posting."""

from __future__ import annotations

import pytest

from config.settings import get_settings
from src.agent.domain import load_domain_config
from src.storage import queries
from src.storage.db import init_db, make_engine, make_sessionmaker
from src.telephony.live_session import _tailored_setup


async def _seed_posting(db_url: str, questions: list[dict]) -> int:
    engine = make_engine(db_url)
    await init_db(engine)
    async with make_sessionmaker(engine)() as session:
        posting = await queries.create_job_posting(
            session, title="Frontend Engineer", domain="screening",
            description="React/TS role", questions=questions,
        )
    await engine.dispose()
    return posting.id


@pytest.mark.asyncio
async def test_tailored_setup_overlays_questions_and_uses_posting_domain(tmp_path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'jd.db'}"
    # .env DOMAIN is helpdesk, but a screening posting must still run under screening.
    settings = get_settings().model_copy(update={"database_url": db_url, "domain": "helpdesk"})
    posting_id = await _seed_posting(db_url, [
        {"id": "q1", "text": "Years with React?", "slot": "years_react", "enabled": True},
        {"id": "q2", "text": "Disabled one?", "slot": "skip", "enabled": False},
    ])

    new_settings, domain = await _tailored_setup(settings, posting_id)

    assert new_settings.domain == "screening"                  # posting's domain wins over .env
    states = domain.flow["states"]
    question_prompts = [s["prompt"] for s in states if s["type"] == "question"]
    assert question_prompts == ["Years with React?"]          # enabled only
    assert any(s["type"] == "close" for s in states)           # base tail inherited
    base = load_domain_config("screening", settings.config_dir)
    assert domain.disclosure == base.disclosure                # screening flow, not helpdesk


@pytest.mark.asyncio
async def test_tailored_setup_unknown_posting_raises(tmp_path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'jd.db'}"
    settings = get_settings().model_copy(update={"database_url": db_url})
    # init the (empty) db so get_job_posting returns None rather than erroring on a missing table
    await _seed_posting(db_url, [{"text": "seed", "enabled": True}])

    with pytest.raises(ValueError, match="not found"):
        await _tailored_setup(settings, 9999)
