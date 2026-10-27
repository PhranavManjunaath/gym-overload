"""Tests for tools.py - what the agent sees. Every number must come from the engine or the DB."""
import datetime as dt
import json
from pathlib import Path
from typing import Iterator

import pytest
from sqlalchemy.orm import Session

import db as storage
import tools

TODAY = dt.date(2026, 10, 27)


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    engine = storage.get_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    with storage.make_session_factory(engine)() as s:
        yield s
    engine.dispose()


def _setup(session: Session, *names: str, **kwargs) -> None:
    for n in names:
        assert tools.add_exercise(session, n, **kwargs)["status"] == "ok"
    session.commit()


def _log(session: Session, *lines: str) -> None:
    for line in lines:
        r = tools.log_workout(session, line, today=TODAY)
        assert r["status"] == "ok", r
        session.commit()


# ---------- add / list exercises ----------

def test_add_exercise_returns_settings(session: Session) -> None:
    r = tools.add_exercise(session, "Bench Press")
    assert r == {"status": "ok", "exercise": "bench press", "equipment": "barbell",
                 "settings": {"rep_min": 6, "rep_max": 10, "increment_kg": 2.5, "target_sets": 3}}


def test_add_exercise_errors_are_returned_not_raised(session: Session) -> None:
    r = tools.add_exercise(session, "leg press", equipment="machine")
    assert r["status"] == "error" and "increment" in r["message"]
    _setup(session, "bench")
    assert tools.add_exercise(session, "bench")["status"] == "error"


def test_list_exercises(session: Session) -> None:
    _setup(session, "squat", "bench")
    _setup(session, "db curl", equipment="dumbbell")
    r = tools.list_exercises(session)
    assert [e["exercise"] for e in r["exercises"]] == ["bench", "db curl", "squat"]
    assert r["exercises"][1]["settings"]["increment_kg"] == 2.0


# ---------- log_workout ----------

def test_log_workout_saves_and_echoes_numbers(session: Session) -> None:
    _setup(session, "bench")
    r = tools.log_workout(session, "bench 60x10,9,8 @8", today=TODAY)
    assert r["status"] == "ok"
    [entry] = r["logged"]
    assert entry["exercise"] == "bench" and entry["date"] == "2026-10-27"
    assert entry["sets"] == [{"weight_kg": 60.0, "reps": 10, "rpe": 8.0},
                             {"weight_kg": 60.0, "reps": 9, "rpe": 8.0},
                             {"weight_kg": 60.0, "reps": 8, "rpe": 8.0}]
    assert (entry["total_reps"], entry["volume_kg"], entry["working_weight_kg"]) == (27, 1620.0, 60.0)
    session.commit()
    assert len(storage.get_history(session, "bench")) == 1


def test_log_workout_parse_error(session: Session) -> None:
    r = tools.log_workout(session, "bench 62,5x10", today=TODAY)
    assert r["status"] == "parse_error" and "couldn't read" in r["message"]


def test_log_workout_unknown_exercise_saves_nothing(session: Session) -> None:
    _setup(session, "bench")
    r = tools.log_workout(session, "bench 60x10\nsquat 100x5", today=TODAY)
    assert r == {"status": "unknown_exercise", "exercises": ["squat"],
                 "message": "Nothing saved. Set these exercises up first (add_exercise), then log again."}
    session.commit()
    assert storage.get_history(session, "bench") == []


def test_log_workout_invalid_value_saves_nothing(session: Session) -> None:
    _setup(session, "bench", "squat")
    r = tools.log_workout(session, "bench 60x10\nsquat 0x5", today=TODAY)
    assert r["status"] == "error" and r["message"].startswith("Nothing saved")
    session.commit()
    assert storage.get_history(session, "bench") == []
    assert storage.get_exercise(session, "bench") is not None   # earlier committed setup survives


def test_log_workout_multiple_exercises(session: Session) -> None:
    _setup(session, "bench", "squat")
    r = tools.log_workout(session, "bench 60x10; squat 100x5,5,5 deload yesterday", today=TODAY)
    assert [(e["exercise"], e["date"], e["deload"]) for e in r["logged"]] == \
        [("bench", "2026-10-27", False), ("squat", "2026-10-26", True)]


# ---------- recommend_next: every rule, always with its numbers ----------

def test_recommend_unknown_exercise(session: Session) -> None:
    assert tools.recommend_next(session, "bench")["status"] == "unknown_exercise"


def test_recommend_no_history_asks_for_starting_weight(session: Session) -> None:
    _setup(session, "bench")
    r = tools.recommend_next(session, "bench")
    assert r["status"] == "need_starting_weight" and "never guess" in r["message"]
    assert "next" not in r


def test_recommend_increase_weight(session: Session) -> None:
    _setup(session, "bench")
    _log(session, "bench 60x10,10,10 @8 2026-10-20")
    r = tools.recommend_next(session, "bench")
    assert r["status"] == "ok" and r["rule"] == "increase_weight"
    assert r["next"] == {"weight_kg": 62.5, "target_reps": [6, 6, 6]}
    assert "add 2.5 kg" in r["rule_explained"]
    last = r["based_on"]["last_session"]
    assert last["date"] == "2026-10-20" and [s["reps"] for s in last["sets"]] == [10, 10, 10]
    assert r["based_on"]["settings"] == {"rep_min": 6, "rep_max": 10, "increment_kg": 2.5, "target_sets": 3}
    assert r["e1rm_last_kg"] == 80.0


def test_recommend_add_reps(session: Session) -> None:
    _setup(session, "bench")
    _log(session, "bench 60x10,9,8 2026-10-20")
    r = tools.recommend_next(session, "bench")
    assert (r["rule"], r["next"]) == ("add_reps", {"weight_kg": 60.0, "target_reps": [10, 10, 9]})


def test_recommend_repeat(session: Session) -> None:
    _setup(session, "bench")
    _log(session, "bench 60x7,6,5 2026-10-20")
    r = tools.recommend_next(session, "bench")
    assert (r["rule"], r["next"]["weight_kg"]) == ("repeat", 60.0)
    assert "under 6 reps" in r["rule_explained"]


def test_recommend_reduce_weight_shows_both_failed_sessions(session: Session) -> None:
    _setup(session, "bench")
    _log(session, "bench 60x7,6,5 2026-10-20", "bench 60x6,5,5 2026-10-23")
    r = tools.recommend_next(session, "bench")
    assert (r["rule"], r["next"]["weight_kg"]) == ("reduce_weight", 55.0)
    assert "95% of that weight, rounded down to a multiple of 2.5 kg" in r["rule_explained"]
    assert [s["total_reps"] for s in r["based_on"]["recent_sessions"]] == [18, 16]


def test_recommend_deload_shows_plateau_window(session: Session) -> None:
    _setup(session, "bench")
    _log(session, "bench 62.5x7,7,7 2026-10-13", "bench 62.5x7,7,7 2026-10-16",
         "bench 62.5x7,7,6 2026-10-20")
    r = tools.recommend_next(session, "bench")
    assert (r["rule"], r["next"]["weight_kg"]) == ("deload", 55.0)
    assert "90%" in r["rule_explained"]
    recent = r["based_on"]["recent_sessions"]
    assert [(s["working_weight_kg"], s["total_reps"]) for s in recent] == [(62.5, 21), (62.5, 21), (62.5, 20)]


def test_recommend_resume_after_deload(session: Session) -> None:
    _setup(session, "bench")
    _log(session, "bench 62.5x7,7,7 2026-10-13", "bench 62.5x7,7,7 2026-10-16",
         "bench 62.5x7,7,6 2026-10-20", "bench 55x6,6,6 deload 2026-10-23")
    r = tools.recommend_next(session, "bench")
    assert (r["rule"], r["next"]["weight_kg"]) == ("resume", 62.5)
    assert r["based_on"]["last_session"]["deload"] is True


def test_recommend_dumbbell_uses_2kg(session: Session) -> None:
    _setup(session, "db curl", equipment="dumbbell", rep_min=8, rep_max=12)
    _log(session, "db curl 12x12,12,12 2026-10-20")
    r = tools.recommend_next(session, "db curl")
    assert r["next"] == {"weight_kg": 14.0, "target_reps": [8, 8, 8]}
    assert "add 2 kg" in r["rule_explained"]


# ---------- plan_first_session ----------

def test_plan_first_session_uses_user_weight(session: Session) -> None:
    _setup(session, "bench")
    r = tools.plan_first_session(session, "bench", 40)
    assert r["status"] == "ok" and r["rule"] == "starting_weight"
    assert r["next"] == {"weight_kg": 40.0, "target_reps": [6, 6, 6]}
    assert r["based_on"]["starting_weight_from"] == "user"


def test_plan_first_session_guards(session: Session) -> None:
    assert tools.plan_first_session(session, "bench", 40)["status"] == "unknown_exercise"
    _setup(session, "bench")
    assert tools.plan_first_session(session, "bench", 0)["status"] == "error"
    _log(session, "bench 60x10 2026-10-20")
    r = tools.plan_first_session(session, "bench", 40)
    assert r["status"] == "error" and "recommend_next" in r["message"]


# ---------- get_progress ----------

def test_get_progress(session: Session) -> None:
    _setup(session, "bench")
    _log(session, "bench 60x10,9,8 2026-10-20", "bench 60x10,10,10 2026-10-23", "bench 62.5x8,7,6 2026-10-27")
    r = tools.get_progress(session, "bench")
    assert [s["date"] for s in r["sessions"]] == ["2026-10-20", "2026-10-23", "2026-10-27"]
    first = r["sessions"][0]
    assert (first["working_weight_kg"], first["total_reps"], first["volume_kg"], first["best_e1rm_kg"]) == \
        (60.0, 27, 1620.0, 80.0)
    assert len(tools.get_progress(session, "bench", last_n=2)["sessions"]) == 2
    assert tools.get_progress(session, "bench", last_n=0)["status"] == "error"
    assert tools.get_progress(session, "squat")["status"] == "unknown_exercise"


# ---------- every result is plain JSON for the agent ----------

def test_all_results_are_json_serializable(session: Session) -> None:
    _setup(session, "bench")
    _log(session, "bench 60x10,10,10 @8 2026-10-20")
    for r in [tools.list_exercises(session), tools.recommend_next(session, "bench"),
              tools.get_progress(session, "bench"), tools.log_workout(session, "bad", today=TODAY),
              tools.recommend_next(session, "nope")]:
        json.dumps(r)
