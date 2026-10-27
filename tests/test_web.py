"""Tests for the app (dashboard.py + web/ pages) with Streamlit AppTest on a throwaway SQLite DB."""
import datetime as dt
import re
from pathlib import Path
from typing import Iterator

import pytest
import streamlit as st
from langchain_core.messages import AIMessage
from streamlit.testing.v1 import AppTest

import agent
import db as storage
import tools
from tests.test_agent import ScriptedLLM, call

ROOT = Path(__file__).resolve().parent.parent
TODAY = dt.date.today()


@pytest.fixture(autouse=True)
def db_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    url = f"sqlite:///{(tmp_path / 'web.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)      # beats .env, so the real database is never touched
    monkeypatch.setenv("WEB_PASSWORD", "")       # no login unless a test sets one
    st.cache_resource.clear()
    yield url
    st.cache_resource.clear()


def seed(url: str, *logs: str, exercises=("bench", "squat")) -> None:
    engine = storage.get_engine(url)
    with storage.make_session_factory(engine).begin() as s:
        for name in exercises:
            tools.add_exercise(s, name)
        for line in logs:
            assert tools.log_workout(s, line, today=TODAY)["status"] == "ok"
    engine.dispose()


def history(url: str, name: str) -> list:
    engine = storage.get_engine(url)
    with storage.make_session_factory(engine)() as s:
        h = storage.get_history(s, name)
    engine.dispose()
    return h


def page(name: str) -> AppTest:
    at = AppTest.from_file(str(ROOT / "web" / f"{name}.py"), default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    return at


def codes(at: AppTest) -> str:
    return "\n".join(c.value for c in at.code)


def button(at: AppTest, label: str):
    return next(b for b in at.button if b.label == label)


# ---------- Log workout ----------

def test_log_preview_before_saving(db_url: str) -> None:
    seed(db_url)
    at = page("log")
    at.text_area[0].input("bench 60x10,10,10 @8").run()
    assert "60 kg × 10, 10, 10 (RPE 8, 8, 8)" in codes(at)
    assert not button(at, "Save").disabled
    assert history(db_url, "bench") == []                      # preview never saves


def test_log_parse_error_is_shown(db_url: str) -> None:
    seed(db_url)
    at = page("log")
    at.text_area[0].input("bench 62,5x10").run()
    assert "couldn't read" in at.error[0].value
    assert not [b for b in at.button if b.label == "Save"]


def test_log_unknown_exercise_disables_save(db_url: str) -> None:
    seed(db_url)
    at = page("log")
    at.text_area[0].input("deadlift 120x5").run()
    assert "Not set up yet: deadlift" in at.warning[0].value
    assert button(at, "Save").disabled


def test_log_save_stores_and_shows_next_target(db_url: str) -> None:
    seed(db_url)
    at = page("log")
    at.text_area[0].input("bench 60x10,10,10").run()
    button(at, "Save").click().run()
    assert not at.exception
    assert at.success[0].value == "Saved!"
    out = codes(at)
    assert f"Saved bench {TODAY.isoformat()}: 60 kg × 10, 10, 10" in out
    assert "Next bench: 62.5 kg × 6, 6, 6" in out and "Rule: increase_weight" in out
    assert at.text_area[0].value == ""                          # cleared, so it can't be saved again
    assert len(history(db_url, "bench")) == 1


# ---------- Next session ----------

def test_next_shows_targets_and_evidence(db_url: str) -> None:
    seed(db_url, "bench 60x10,10,10")
    at = page("next")
    assert any(m.value == "### 62.5 kg × 6, 6, 6" for m in at.markdown)
    assert "Based on:" in codes(at)


def test_next_asks_for_starting_weight_never_guesses(db_url: str) -> None:
    seed(db_url, "bench 60x10,10,10")
    at = page("next")
    start = at.number_input(key="start_squat")
    assert start.value is None
    assert "Next squat" not in codes(at)
    start.set_value(40).run()
    assert "Next squat: 40 kg × 6, 6, 6" in codes(at)
    assert "starting weight you gave" in codes(at)


def test_next_without_exercises(db_url: str) -> None:
    assert "No exercises yet" in page("next").info[0].value


# ---------- Exercises ----------

def test_add_exercise(db_url: str) -> None:
    at = page("exercises")
    at.text_input[0].input("Bench Press")
    button(at, "Add").click().run()
    assert not at.exception
    assert at.success[0].value == "Added bench press."
    assert at.dataframe[0].value["Exercise"].tolist() == ["bench press"]
    assert at.dataframe[0].value["Jump (kg)"].tolist() == [2.5]


def test_add_machine_without_jump_shows_error(db_url: str) -> None:
    at = page("exercises")
    at.text_input[0].input("leg press")
    at.selectbox[0].select("machine")
    button(at, "Add").click().run()
    assert "No default increment" in at.error[0].value


# ---------- Progress ----------

def test_progress_empty(db_url: str) -> None:
    storage.get_engine(db_url).dispose()
    assert "No exercises yet" in page("progress").info[0].value


def test_progress_metrics_and_history(db_url: str) -> None:
    seed(db_url, "bench 60x10,9,8 2026-10-20", "bench 60x10,10,10 2026-10-23")
    at = page("progress")
    assert at.selectbox[0].options == ["bench", "squat"]
    assert any("62.5 kg × 6, 6, 6" in m.value for m in at.markdown)
    assert [m.label for m in at.metric][:3] == ["🔥 Training streak", "Best streak",
                                                "Consistency (last 4 weeks)"]
    assert [m.value for m in at.metric][3:] == ["60 kg", "30", "1800 kg", "80 kg"]
    assert len(at.dataframe[0].value) == 2
    assert [b.label for b in at.get("download_button")] == ["⬇️ Workouts CSV", "⬇️ Meals CSV"]
    at.selectbox[0].select("squat").run()
    assert not at.exception
    assert "starting weight" in at.info[0].value


# ---------- AI coach ----------

def test_coach_chat_shows_numbers_used(db_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    seed(db_url)
    llm = ScriptedLLM(script=[
        call("log_workout", text="bench 60x10,10,10"),
        call("recommend_next", exercise="bench"),
        AIMessage("Nice! Next time 62.5 kg for 6 reps."),
    ], seen=[])
    monkeypatch.setattr(agent, "build_llm", lambda: llm)
    at = page("coach")
    at.chat_input[0].set_value("bench 60x10,10,10").run()
    assert not at.exception
    reply = at.chat_message[-1].markdown[0].value
    assert reply.startswith("Nice! Next time 62.5 kg") and "📊 Numbers used" in reply
    assert len(history(db_url, "bench")) == 1
    assert at.session_state.chat_id.startswith("web-")         # own conversation, not Telegram's


def test_coach_without_groq_key(db_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    def no_key():
        raise RuntimeError("GROQ_API_KEY is missing from .env")
    monkeypatch.setattr(agent, "build_llm", no_key)
    at = page("coach")
    at.chat_input[0].set_value("hi").run()
    assert "isn't set up" in at.chat_message[-1].markdown[0].value


# ---------- login + navigation ----------

def test_password_gate(db_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEB_PASSWORD", "secret123")
    at = AppTest.from_file(str(ROOT / "dashboard.py"), default_timeout=30)
    at.run()
    assert [t.label for t in at.text_input] == ["Password"]
    at.text_input[0].input("wrong")
    button(at, "Log in").click().run()
    assert at.error[0].value == "Wrong password."
    assert not at.text_area                                     # app still hidden
    at.text_input[0].input("secret123")
    button(at, "Log in").click().run()
    assert not at.exception
    assert at.title[0].value == "📝 Log workout"                  # default page is shown


def test_no_password_opens_app(db_url: str) -> None:
    at = AppTest.from_file(str(ROOT / "dashboard.py"), default_timeout=30)
    at.run()
    assert not at.exception
    assert at.title[0].value == "📝 Log workout"


# ---------- separate from the bot ----------

def test_app_never_imports_bot() -> None:
    for f in [ROOT / "dashboard.py", *sorted((ROOT / "web").glob("*.py"))]:
        src = f.read_text(encoding="utf-8")
        assert not re.search(r"^\s*(import bot\b|from bot\b)", src, re.M), f"{f.name} imports bot.py"
