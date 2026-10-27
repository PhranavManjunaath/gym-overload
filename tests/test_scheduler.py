"""Tests for scheduler.py - settings, reminder texts and job setup (nothing is actually scheduled)."""
import asyncio
import datetime as dt
from pathlib import Path
from typing import Iterator, List

import pytest
from sqlalchemy.orm import Session, sessionmaker

import db as storage
import scheduler
import tools

TODAY = dt.date(2026, 10, 27)


@pytest.fixture
def SessionLocal(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    engine = storage.get_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    yield storage.make_session_factory(engine)
    engine.dispose()


# ---------- settings ----------

def test_default_settings() -> None:
    s = scheduler.ReminderSettings.from_env({})
    assert (s.timezone, s.workout_days, s.workout_time, s.missed_check_time) == \
        ("Asia/Kolkata", ["mon", "wed", "fri"], dt.time(7), dt.time(21))
    assert s.meal_times == [dt.time(8), dt.time(13), dt.time(20)]


def test_settings_from_env() -> None:
    s = scheduler.ReminderSettings.from_env({
        "REMINDER_TIMEZONE": "Europe/London", "WORKOUT_DAYS": "Saturday, tue,TUE",
        "WORKOUT_REMINDER_TIME": "18:30", "MISSED_WORKOUT_CHECK_TIME": "22:15", "MEAL_REMINDER_TIMES": "",
    })
    assert (s.timezone, s.workout_days, s.workout_time, s.missed_check_time, s.meal_times) == \
        ("Europe/London", ["tue", "sat"], dt.time(18, 30), dt.time(22, 15), [])


@pytest.mark.parametrize("env", [
    {"REMINDER_TIMEZONE": "Mars/Base"},
    {"WORKOUT_DAYS": "funday"},
    {"WORKOUT_DAYS": " , "},
    {"WORKOUT_REMINDER_TIME": "7am"},
    {"MEAL_REMINDER_TIMES": "08:00,25:00"},
])
def test_bad_settings_rejected(env: dict) -> None:
    with pytest.raises(ValueError):
        scheduler.ReminderSettings.from_env(env)


# ---------- texts ----------

def test_workout_reminder_uses_engine_targets(SessionLocal: sessionmaker[Session]) -> None:
    with SessionLocal.begin() as s:
        tools.add_exercise(s, "bench")
        tools.add_exercise(s, "squat")
        tools.log_workout(s, "bench 60x10,10,10", today=TODAY)
    with SessionLocal() as s:
        text = scheduler.workout_reminder_text(s)
    assert "bench: 62.5 kg × 6, 6, 6 (increase_weight)" in text
    assert "squat: no history yet - tell me your starting weight" in text


def test_workout_reminder_without_exercises(SessionLocal: sessionmaker[Session]) -> None:
    with SessionLocal() as s:
        assert "Add your exercises" in scheduler.workout_reminder_text(s)


def test_missed_workout_only_when_nothing_logged(SessionLocal: sessionmaker[Session]) -> None:
    with SessionLocal.begin() as s:
        tools.add_exercise(s, "bench")
    with SessionLocal() as s:
        assert scheduler.missed_workout_text(s, TODAY) is not None
    with SessionLocal.begin() as s:
        tools.log_workout(s, "bench 60x10", today=TODAY)
    with SessionLocal() as s:
        assert scheduler.missed_workout_text(s, TODAY) is None


@pytest.mark.parametrize("t, meal", [(dt.time(8), "Breakfast"), (dt.time(13), "Lunch"), (dt.time(20), "Dinner")])
def test_meal_reminder_text(t: dt.time, meal: str) -> None:
    assert scheduler.meal_reminder_text(t).startswith(f"🍽 {meal} time")


def test_describe() -> None:
    text = scheduler.describe(scheduler.ReminderSettings.from_env({}))
    assert "mon, wed, fri at 07:00" in text and "08:00, 13:00, 20:00" in text


# ---------- jobs ----------

def test_build_scheduler_registers_jobs(SessionLocal: sessionmaker[Session]) -> None:
    sent: List[str] = []

    async def send(text: str) -> None:
        sent.append(text)

    sched = scheduler.build_scheduler(send, SessionLocal, scheduler.ReminderSettings.from_env({}))
    jobs = {j.id: j for j in sched.get_jobs()}
    assert set(jobs) == {"workout_reminder", "missed_workout_check", "meal_0800", "meal_1300", "meal_2000"}
    assert "day_of_week='mon,wed,fri'" in str(jobs["workout_reminder"].trigger)
    assert "hour='7'" in str(jobs["workout_reminder"].trigger)

    asyncio.run(jobs["workout_reminder"].func())
    asyncio.run(jobs["meal_1300"].func())
    assert sent[0].startswith("🏋️ Workout day!") and sent[1].startswith("🍽 Lunch time")
