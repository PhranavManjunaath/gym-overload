"""Tests for api.py - the website's HTTP layer. Throwaway SQLite, fake LLM, no network."""
import datetime as dt
from pathlib import Path
from typing import Iterator

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from sqlalchemy.orm import Session, sessionmaker

import agent
import api
import db as storage
import tools
from tests.test_agent import ScriptedLLM, call

TODAY = dt.date(2026, 10, 27)


@pytest.fixture
def SessionLocal(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    engine = storage.get_engine(f"sqlite:///{(tmp_path / 'api.db').as_posix()}")
    yield storage.make_session_factory(engine)
    engine.dispose()


def client(SessionLocal: sessionmaker[Session], script=None, password: str = "") -> TestClient:
    factory = lambda: agent.Coach(ScriptedLLM(script=script or [], seen=[]), SessionLocal, today=lambda: TODAY)
    return TestClient(api.create_app(SessionLocal, factory, password=password, today=lambda: TODAY))


def seed(SessionLocal: sessionmaker[Session], *logs: str) -> None:
    with SessionLocal.begin() as s:
        tools.add_exercise(s, "bench")
        tools.add_exercise(s, "squat")
        for line in logs:
            assert tools.log_workout(s, line, today=TODAY)["status"] == "ok"


# ---------- basics ----------

def test_health_and_meta(SessionLocal: sessionmaker[Session]) -> None:
    c = client(SessionLocal)
    assert c.get("/api/health").json() == {"status": "ok"}
    assert c.get("/api/auth").json() == {"status": "ok", "password_required": False}
    meta = c.get("/api/meta").json()
    assert "bench 60x10,10,9" in meta["log_help"]
    assert meta["defaults"] == {"rep_min": 6, "rep_max": 10, "target_sets": 3}
    assert meta["default_increments_kg"] == {"barbell": 2.5, "dumbbell": 2.0}


def test_password_required_when_set(SessionLocal: sessionmaker[Session]) -> None:
    c = client(SessionLocal, password="secret123")
    assert c.get("/api/auth").json()["password_required"] is True
    assert c.get("/api/health").status_code == 200
    assert c.get("/api/exercises").status_code == 401
    assert c.get("/api/exercises", headers={"X-App-Password": "wrong"}).status_code == 401
    assert c.get("/api/exercises", headers={"X-App-Password": "secret123"}).status_code == 200


# ---------- exercises ----------

def test_add_and_list_exercises(SessionLocal: sessionmaker[Session]) -> None:
    c = client(SessionLocal)
    r = c.post("/api/exercises", json={"name": "DB Curl", "equipment": "dumbbell", "rep_min": 8, "rep_max": 12})
    assert r.json()["settings"] == {"rep_min": 8, "rep_max": 12, "increment_kg": 2.0, "target_sets": 3}
    bad = c.post("/api/exercises", json={"name": "leg press", "equipment": "machine"}).json()
    assert bad["status"] == "error" and "No default increment" in bad["message"]
    assert [e["exercise"] for e in c.get("/api/exercises").json()["exercises"]] == ["db curl"]


# ---------- logging ----------

def test_preview_never_saves(SessionLocal: sessionmaker[Session]) -> None:
    seed(SessionLocal)
    c = client(SessionLocal)
    r = c.post("/api/workouts/preview", json={"text": "bench 60x10,10,9 @8\ndeadlift 120x5"}).json()
    assert r["status"] == "ok"
    assert r["entries"][0] == {"exercise": "bench", "date": "2026-10-27", "deload": False, "sets": [
        {"weight_kg": 60.0, "reps": 10, "rpe": 8.0}, {"weight_kg": 60.0, "reps": 10, "rpe": 8.0},
        {"weight_kg": 60.0, "reps": 9, "rpe": 8.0}]}
    assert r["unknown_exercises"] == ["deadlift"]
    with SessionLocal() as s:
        assert storage.get_history(s, "bench") == []


def test_preview_parse_error(SessionLocal: sessionmaker[Session]) -> None:
    r = client(SessionLocal).post("/api/workouts/preview", json={"text": "bench 62,5x10"}).json()
    assert r["status"] == "parse_error" and "couldn't read" in r["message"]


def test_future_date_rejected(SessionLocal: sessionmaker[Session]) -> None:
    c = client(SessionLocal)
    assert c.post("/api/workouts/preview", json={"text": "bench 60x10", "date": "2026-10-28"}).status_code == 422


def test_save_returns_logged_and_next(SessionLocal: sessionmaker[Session]) -> None:
    seed(SessionLocal)
    r = client(SessionLocal).post("/api/workouts", json={"text": "bench 60x10,10,10", "date": "2026-10-26"}).json()
    assert r["status"] == "ok"
    assert r["logged"][0]["date"] == "2026-10-26"
    rec = r["recommendations"][0]
    assert (rec["rule"], rec["next"]) == ("increase_weight", {"weight_kg": 62.5, "target_reps": [6, 6, 6]})
    with SessionLocal() as s:
        assert len(storage.get_history(s, "bench")) == 1


def test_save_unknown_exercise_saves_nothing(SessionLocal: sessionmaker[Session]) -> None:
    seed(SessionLocal)
    r = client(SessionLocal).post("/api/workouts", json={"text": "bench 60x10\ndeadlift 100x5"}).json()
    assert r["status"] == "unknown_exercise"
    with SessionLocal() as s:
        assert storage.get_history(s, "bench") == []


# ---------- next / progress / dashboard ----------

def test_next_and_first_session(SessionLocal: sessionmaker[Session]) -> None:
    seed(SessionLocal, "bench 60x10,10,10")
    c = client(SessionLocal)
    recs = c.get("/api/next").json()["recommendations"]
    assert [(r["exercise"], r["status"]) for r in recs] == [("bench", "ok"), ("squat", "need_starting_weight")]
    assert c.get("/api/exercises/bench/next").json()["based_on"]["last_session"]["sets"][0]["reps"] == 10
    plan = c.post("/api/exercises/squat/first-session", json={"starting_weight_kg": 60}).json()
    assert plan["next"] == {"weight_kg": 60.0, "target_reps": [6, 6, 6]} and plan["rule"] == "starting_weight"
    assert c.get("/api/exercises/deadlift/next").json()["status"] == "unknown_exercise"


def test_progress(SessionLocal: sessionmaker[Session]) -> None:
    seed(SessionLocal, "bench 60x10,9,8 2026-10-20", "bench 60x10,10,10 2026-10-23")
    c = client(SessionLocal)
    s = c.get("/api/exercises/bench/progress").json()["sessions"]
    assert [(x["date"], x["volume_kg"], x["best_e1rm_kg"]) for x in s] == \
        [("2026-10-20", 1620.0, 80.0), ("2026-10-23", 1800.0, 80.0)]
    assert len(c.get("/api/exercises/bench/progress?last_n=1").json()["sessions"]) == 1


def test_dashboard(SessionLocal: sessionmaker[Session]) -> None:
    seed(SessionLocal, "bench 60x10,9,8 2026-10-20", "squat 100x5,5,5 2026-10-22", "bench 60x10,10,10 2026-10-23")
    d = client(SessionLocal).get("/api/dashboard").json()
    assert [e["exercise"] for e in d["exercises"]] == ["bench", "squat"]
    assert [n["status"] for n in d["next"]] == ["ok", "ok"]
    assert [(x["date"], x["exercise"]) for x in d["recent"]] == \
        [("2026-10-23", "bench"), ("2026-10-22", "squat"), ("2026-10-20", "bench")]


def test_dashboard_empty(SessionLocal: sessionmaker[Session]) -> None:
    d = client(SessionLocal).get("/api/dashboard").json()
    assert (d["exercises"], d["next"], d["recent"]) == ([], [], [])
    assert d["streak"]["current_streak"] == 0 and d["protein"]["meals"] == []


# ---------- coach ----------

def test_coach_splits_reply_and_evidence(SessionLocal: sessionmaker[Session]) -> None:
    seed(SessionLocal)
    c = client(SessionLocal, script=[
        call("log_workout", text="bench 60x10,10,10"),
        call("recommend_next", exercise="bench"),
        AIMessage("Nice! Next time 62.5 kg for 6 reps."),
    ])
    r = c.post("/api/coach", json={"message": "bench 60x10,10,10", "conversation_id": "abc12345"}).json()
    assert r["status"] == "ok"
    assert r["reply"] == "Nice! Next time 62.5 kg for 6 reps."
    assert "Next bench: 62.5 kg × 6, 6, 6" in r["evidence"]


def test_coach_without_key(SessionLocal: sessionmaker[Session]) -> None:
    def no_key():
        raise RuntimeError("GROQ_API_KEY is missing from .env")
    app = api.create_app(SessionLocal, no_key, password="", today=lambda: TODAY)
    r = TestClient(app).post("/api/coach", json={"message": "hi", "conversation_id": "abc12345"}).json()
    assert r["status"] == "error" and "isn't set up" in r["message"]


def test_coach_rejects_bad_conversation_id(SessionLocal: sessionmaker[Session]) -> None:
    r = client(SessionLocal).post("/api/coach", json={"message": "hi", "conversation_id": "../etc"})
    assert r.status_code == 422


# ---------- reminders + separation ----------

def test_reminders_read_only(SessionLocal: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch) -> None:
    for k in ["REMINDER_TIMEZONE", "WORKOUT_DAYS", "WORKOUT_REMINDER_TIME", "MISSED_WORKOUT_CHECK_TIME",
              "MEAL_REMINDER_TIMES"]:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.delenv("WEEKLY_REPORT_TIME", raising=False)
    c = client(SessionLocal)
    r = c.get("/api/reminders").json()
    assert {k: r[k] for k in ["timezone", "workout_days", "workout_time", "missed_check_time",
                              "weekly_report_time", "meal_times", "daily_cap"]} == {
        "timezone": "Asia/Kolkata", "workout_days": ["mon", "wed", "fri"], "workout_time": "07:00",
        "missed_check_time": "21:00", "weekly_report_time": "19:00", "meal_times": ["08:00", "13:00", "20:00"],
        "daily_cap": 2}
    assert c.post("/api/reminders").status_code == 405          # edited via /api/settings instead


# ---------- Phase 4/5 endpoints ----------

def test_settings_round_trip_and_all_or_nothing(SessionLocal: sessionmaker[Session],
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    for k in ["WORKOUT_DAYS", "WORKOUT_REMINDER_TIME"]:
        monkeypatch.delenv(k, raising=False)
    c = client(SessionLocal)
    s = c.post("/api/settings", json={"training_days": "tue,thu", "workout_time": "18:30",
                                      "protein_target_g": 140, "goal": "bench 100 kg"}).json()
    assert (s["training_days"], s["workout_time"], s["protein_target_g"], s["goal"]) == \
        (["tue", "thu"], "18:30", 140.0, "bench 100 kg")
    bad = c.post("/api/settings", json={"training_days": "mon", "protein_target_g": 0}).json()
    assert bad["status"] == "error"
    assert c.get("/api/settings").json()["training_days"] == ["tue", "thu"]      # nothing half-saved
    assert c.get("/api/reminders").json()["workout_days"] == ["tue", "thu"]


def test_meals_endpoints(SessionLocal: sessionmaker[Session]) -> None:
    c = client(SessionLocal)
    m = c.post("/api/meals", json={"text": "2 eggs + 1 scoop whey"}).json()
    assert (m["meal"]["protein_g"], m["meal"]["protein_estimated"]) == (36.0, True)
    fixed = c.post(f"/api/meals/{m['meal']['id']}/protein", json={"protein_g": 40}).json()
    assert fixed["day"]["total_protein_g"] == 40.0
    assert [x["protein_estimated"] for x in c.get("/api/meals").json()["meals"]] == [False]


def test_streak_report_and_export(SessionLocal: sessionmaker[Session]) -> None:
    seed(SessionLocal, "bench 60x10,10,10 2026-10-26")
    c = client(SessionLocal)
    assert c.get("/api/streak").json()["current_streak"] == 1
    rep = c.get("/api/report").json()
    assert rep["sessions_logged"] == 1 and rep["text"].startswith("📅 Week 2026-10-26 to 2026-11-01")
    csv_resp = c.get("/api/export/workouts.csv")
    assert csv_resp.headers["content-type"].startswith("text/csv")
    assert "attachment" in csv_resp.headers["content-disposition"]
    assert csv_resp.text.splitlines()[1].startswith("2026-10-26,bench,1,60.0,10")
    assert c.get("/api/export/passwords.csv").status_code == 404


def test_api_never_imports_bot() -> None:
    src = (Path(__file__).resolve().parent.parent / "api.py").read_text(encoding="utf-8")
    assert "import bot" not in src and "from bot" not in src
