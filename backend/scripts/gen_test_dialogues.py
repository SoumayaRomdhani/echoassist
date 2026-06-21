"""Generate synthetic screening dialogues with ground-truth notes.

Writes data/eval/dialogues.json — used by eval/notes_eval.py to measure notes
extraction accuracy, and by finalize_call.py for the persistence demo. Each
ground-truth field lists acceptable substrings (case-insensitive), since
free-text answers vary in wording.

    python scripts/gen_test_dialogues.py
"""

from __future__ import annotations

import json

from config.settings import get_settings
from src.console import bold, init_console


def _turns(pairs: list[tuple[str, str]]) -> list[dict]:
    out: list[dict] = []
    for question, answer in pairs:
        out.append({"role": "assistant", "text": question})
        out.append({"role": "user", "text": answer})
    return out


_DIALOGUES = [
    {
        "call_id": "testdlg-amina",
        "transcript": _turns([
            ("How many years of professional experience do you have?",
             "I have about six years of professional experience, mostly with Python."),
            ("What's your primary tech stack?",
             "Python with FastAPI, and PostgreSQL for the database."),
            ("When could you start?", "I could start in about three weeks."),
            ("Are you comfortable working remotely, and which time zone are you in?",
             "Yes, fully remote. I'm based in Tunis, Central European Time."),
            ("What are your salary expectations?", "I'm looking for around 75,000 euros."),
        ]),
        "expected_notes": {
            "years_experience": ["6", "six"],
            "primary_stack": ["python", "fastapi"],
            "availability": ["three weeks", "3 weeks"],
            "remote_setup": ["remote", "tunis"],
            "salary_expectation": ["75"],
        },
    },
    {
        "call_id": "testdlg-marc",
        "transcript": _turns([
            ("How many years of professional experience do you have?",
             "Ten years, mainly building backend services in Java."),
            ("What's your primary tech stack?", "Java with Spring Boot, and some Kafka."),
            ("When could you start?", "I'm available immediately."),
            ("Are you comfortable working remotely, and which time zone are you in?",
             "Remote is fine, I'm in Paris, Central European Time."),
            ("What are your salary expectations?", "Around 90,000 euros per year."),
        ]),
        "expected_notes": {
            "years_experience": ["10", "ten"],
            "primary_stack": ["java", "spring"],
            "availability": ["immediate"],
            "remote_setup": ["remote", "paris"],
            "salary_expectation": ["90"],
        },
    },
    {
        "call_id": "testdlg-lina",
        "transcript": _turns([
            ("How many years of professional experience do you have?",
             "I have three years of experience as a frontend developer."),
            ("What's your primary tech stack?", "JavaScript with React, and Node.js."),
            ("When could you start?", "I would need about two months' notice."),
            ("Are you comfortable working remotely, and which time zone are you in?",
             "I'd prefer hybrid, I'm based in Lyon."),
            ("What are your salary expectations?", "Somewhere around 50,000 euros."),
        ]),
        "expected_notes": {
            "years_experience": ["3", "three"],
            "primary_stack": ["javascript", "react"],
            "availability": ["two months", "2 months"],
            "remote_setup": ["hybrid", "lyon"],
            "salary_expectation": ["50"],
        },
    },
]


def main() -> None:
    settings = get_settings()
    init_console()
    out_path = settings.data_dir / "eval" / "dialogues.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(_DIALOGUES, ensure_ascii=False, indent=2), encoding="utf-8")
    print(bold(f"wrote {len(_DIALOGUES)} test dialogues -> {out_path}"))


if __name__ == "__main__":
    main()
