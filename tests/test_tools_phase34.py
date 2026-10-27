"""Tests for the Phase 3/4 tools: history, plateau, summaries, settings, memory, schedule, streaks, meals."""
import datetime as dt
from pathlib import Path
from typing import Iterator

import pytest
from sqlalchemy.orm import Session

import db as storage
import tools

TODAY = dt.date(2026, 10, 27)            # a Tuesday


@pytest.fixture
def session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Session]:
    for k in ["WORKOUT_DAYS", "WORKOUT_REMINDER_TIME"]:
        monkeypatch.delenv(k, raising=False)
    engine = storage.get_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    with storage.make_session_factory(engine)() as s:
        tools.add_exercise(s, "bench")
        s.commit()
        yield s
    engine.dispose()


def _log(session: Session, *lines: str) -> dict:
    r = {}
    for line in lines:
        r = tools.log_workout(session, line, today=TODAY)
        assert r["status"] == "ok", r
    session.commit()
    return r


# ---------- milestones on logging ----------

def test_log_reports_new_e1rm_best(session: Session) -> None:
    first = _log(session, "bench 60x10,10,10 2026-10-20")
    assert first["milestones"] == []                                    # nothing to beat yet
    r = _log(session, "bench 65x8,8,8 2026-10-23")
    assert r["milestones"] == [{"exercise": "bench", "date": "2026-10-23", "e1rm_kg": 82.33,
                                "previous_best_kg": 80.0, "gain_kg": 2.33}]
    assert _log(session, "bench 60x6,6,6 2026-10-26")["milestones"] == []


# ---------- history & analysis ----------

def test_get_history(session: Session) -> None:
    _log(session, "bench 60x10 2026-10-20", "bench 62.5x8 2026-10-23", "bench 62.5x9 2026-10-26")
    r = tools.get_history(session, "bench", n=2)
    assert [s["date"] for s in r["sessions"]] == ["2026-10-23", "2026-10-26"]
    assert tools.get_history(session, "squat")["status"] == "unknown_exercise"
    assert tools.get_history(session, "bench", n=0)["status"] == "error"


def test_check_plateau(session: Session) -> None:
    _log(session, "bench 62.5x7,7,7 2026-10-13", "bench 62.5x7,7,7 2026-10-16", "bench 62.5x7,7,6 2026-10-20")
    r = tools.check_plateau(session, "bench")
    assert r["plateau"] is True and [s["total_reps"] for s in r["sessions_checked"]] == [21, 21, 20]
    _log(session, "bench 62.5x8,7,7 2026-10-23")
    assert tools.check_plateau(session, "bench")["plateau"] is False


def test_check_plateau_without_history(session: Session) -> None:
    assert tools.check_plateau(session, "bench")["status"] == "error"


def test_progress_summary_tool(session: Session) -> None:
    _log(session, "bench 60x10,9,8 2026-10-19", "bench 62.5x8,7,6 2026-10-26")
    r = tools.progress_summary(session, "bench", weeks=2, today=TODAY)
    assert (r["sessions"], r["e1rm_change_kg"], r["volume_change_kg"]) == (2, -0.83, -307.5)
    assert tools.progress_summary(session, "bench", weeks=0)["status"] == "error"


def test_update_exercise_settings(session: Session) -> None:
    r = tools.update_exercise_settings(session, "bench", rep_min=5, rep_max=8)
    assert r["settings"] == {"rep_min": 5, "rep_max": 8, "increment_kg": 2.5, "target_sets": 3}
    bad = tools.update_exercise_settings(session, "bench", rep_min=9)
    assert bad["status"] == "error"
    assert tools.update_exercise_settings(session, "squat", rep_min=3)["status"] == "unknown_exercise"


# ---------- memory, schedule, streak ----------

def test_preferences_goal_and_memory_context(session: Session) -> None:
    assert tools.save_preference(session, "Dislikes", "lunges")["key"] == "dislikes"
    tools.save_preference(session, "dislikes", "lunges, burpees")            # overwrite
    tools.set_goal(session, "bench 100 kg by June")
    tools.set_protein_target(session, 140)
    ctx = tools.memory_context(session)
    assert "Goal: bench 100 kg by June" in ctx
    assert "Preference - dislikes: lunges, burpees" in ctx
    assert "Protein target: 140 g/day" in ctx
    assert "Training days: mon, wed, fri (reminder 07:00)" in ctx


def test_schedule_and_day_plan(session: Session) -> None:
    assert tools.get_schedule(session)["source"] == "defaults"
    r = tools.set_schedule(session, "tue, thu,SAT", "18:30")
    assert (r["training_days"], r["workout_time"], r["source"]) == (["tue", "thu", "sat"], "18:30", "app")
    assert tools.set_schedule(session, "funday")["status"] == "error"
    assert tools.set_day_plan(session, "Tuesday", ["bench"])["exercises"] == ["bench"]
    session.commit()                                                       # each tool call = one transaction
    assert tools.set_day_plan(session, "tue", ["squat"])["status"] == "unknown_exercise"
    assert tools.get_schedule(session)["day_plan"] == {"tue": ["bench"]}


def test_streak_tool(session: Session) -> None:
    tools.set_schedule(session, "mon,wed,fri")
    _log(session, "bench 60x10 2026-10-19", "bench 60x10 2026-10-21", "bench 60x10 2026-10-23",
         "bench 60x10 2026-10-26")
    r = tools.streak(session, today=TODAY)
    assert (r["current_streak"], r["best_streak"], r["logged_today"]) == (4, 4, False)
    assert r["consistency"]["percent"] == 100


# ---------- meals ----------

def test_meal_estimate_and_correction(session: Session) -> None:
    tools.set_protein_target(session, 140)
    r = tools.log_meal(session, "chicken breast 200g, 2 eggs", today=TODAY)
    assert (r["meal"]["protein_g"], r["meal"]["protein_estimated"]) == (74.0, True)
    assert (r["day"]["total_protein_g"], r["day"]["remaining_g"], r["day"]["any_estimated"]) == (74.0, 66.0, True)
    fixed = tools.correct_meal_protein(session, r["meal"]["id"], 70)
    assert (fixed["meal"]["protein_g"], fixed["meal"]["protein_estimated"]) == (70.0, False)
    assert fixed["day"]["total_protein_g"] == 70.0


def test_unknown_meal_is_stored_without_protein(session: Session) -> None:
    r = tools.log_meal(session, "pizza", today=TODAY)
    assert r["meal"]["protein_g"] is None and "Tell me the grams" in r["message"]
    assert r["day"]["meals_missing_protein"] == 1 and r["day"]["target_g"] is None


def test_protein_target_bounds(session: Session) -> None:
    assert tools.set_protein_target(session, 0)["status"] == "error"
    assert tools.correct_meal_protein(session, 999, 10)["status"] == "error"
