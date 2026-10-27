"""Tests for scheduler.py - settings, the 2-per-day planner with fake times, texts and the tick."""
import asyncio
import datetime as dt
from pathlib import Path
from typing import Iterator, List
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.orm import Session, sessionmaker

import db as storage
import scheduler
import tools

TZ = ZoneInfo("Asia/Kolkata")
MWF = ["mon", "wed", "fri"]
S = scheduler.ReminderSettings.from_env({})
MON, TUE, SUN = dt.date(2026, 10, 26), dt.date(2026, 10, 27), dt.date(2026, 11, 1)


def at(day: dt.date, hhmm: str) -> dt.datetime:
    return dt.datetime.combine(day, dt.datetime.strptime(hhmm, "%H:%M").time(), tzinfo=TZ)


def plan(day: dt.date, hhmm: str, sent=(), logged=False, days=MWF, workout="07:00") -> List[str]:
    return scheduler.plan_messages(at(day, hhmm), days, dt.datetime.strptime(workout, "%H:%M").time(),
                                   S, list(sent), logged)


@pytest.fixture
def SessionLocal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[sessionmaker[Session]]:
    for k in ["WORKOUT_DAYS", "WORKOUT_REMINDER_TIME"]:
        monkeypatch.delenv(k, raising=False)
    engine = storage.get_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    yield storage.make_session_factory(engine)
    engine.dispose()


# ---------- settings ----------

def test_default_settings() -> None:
    assert (S.timezone, S.workout_days, S.workout_time, S.missed_check_time, S.weekly_report_time) == \
        ("Asia/Kolkata", ["mon", "wed", "fri"], dt.time(7), dt.time(21), dt.time(19))
    assert S.meal_times == [dt.time(8), dt.time(13), dt.time(20)]


def test_settings_from_env() -> None:
    s = scheduler.ReminderSettings.from_env({
        "REMINDER_TIMEZONE": "Europe/London", "WORKOUT_DAYS": "Saturday, tue,TUE",
        "WORKOUT_REMINDER_TIME": "18:30", "MISSED_WORKOUT_CHECK_TIME": "22:15", "MEAL_REMINDER_TIMES": "",
        "WEEKLY_REPORT_TIME": "20:00",
    })
    assert (s.timezone, s.workout_days, s.workout_time, s.missed_check_time, s.meal_times, s.weekly_report_time) == \
        ("Europe/London", ["tue", "sat"], dt.time(18, 30), dt.time(22, 15), [], dt.time(20))


@pytest.mark.parametrize("env", [
    {"REMINDER_TIMEZONE": "Mars/Base"}, {"WORKOUT_DAYS": "funday"}, {"WORKOUT_DAYS": " , "},
    {"WORKOUT_REMINDER_TIME": "7am"}, {"MEAL_REMINDER_TIMES": "08:00,25:00"},
])
def test_bad_settings_rejected(env: dict) -> None:
    with pytest.raises(ValueError):
        scheduler.ReminderSettings.from_env(env)


# ---------- planner: workout reminder & missed-workout nudge ----------

def test_workout_reminder_on_training_day_at_time() -> None:
    assert plan(MON, "06:59") == []
    assert plan(MON, "07:00") == ["workout_reminder"]
    assert plan(MON, "07:01", sent=["workout_reminder"]) == []           # only once


def test_no_workout_reminder_on_rest_day_or_after_logging() -> None:
    assert plan(TUE, "07:00") == []
    assert plan(MON, "07:00", logged=True) == []


def test_late_start_still_reminds_until_nudge_time() -> None:
    assert plan(MON, "15:00") == ["workout_reminder"]
    assert plan(MON, "21:30") == ["missed_nudge"]                       # past 21:00 - nudge instead


def test_missed_nudge_at_nine_pm_only_if_nothing_logged() -> None:
    assert plan(MON, "20:59", sent=["workout_reminder"]) == []
    assert plan(MON, "21:00", sent=["workout_reminder"]) == ["missed_nudge"]
    assert plan(MON, "21:00", sent=["workout_reminder"], logged=True) == []
    assert plan(MON, "21:05", sent=["workout_reminder", "missed_nudge"]) == []
    assert plan(TUE, "21:00") == []                                     # rest day


def test_custom_schedule_from_app() -> None:
    assert plan(TUE, "18:30", days=["tue", "thu"], workout="18:30") == ["workout_reminder"]


# ---------- planner: 2-per-day cap ----------

def test_cap_two_messages_per_day() -> None:
    assert plan(MON, "21:00", sent=["workout_reminder", "meal_0800"]) == []


def test_meal_reminder_on_rest_day() -> None:
    assert plan(TUE, "08:00") == ["meal_0800"]
    assert plan(TUE, "09:01") == []                                     # stale after an hour
    assert plan(TUE, "13:00", sent=["meal_0800"]) == ["meal_1300"]
    assert plan(TUE, "20:00", sent=["meal_0800", "meal_1300"]) == []    # cap reached


def test_meals_never_take_a_slot_the_nudge_may_need() -> None:
    # Training day, reminder sent, not trained yet: the last slot is kept for a possible nudge.
    assert plan(MON, "08:00", sent=["workout_reminder"]) == []
    assert plan(MON, "13:00", sent=["workout_reminder"], logged=True) == ["meal_1300"]


def test_sunday_weekly_report() -> None:
    assert plan(SUN, "18:59") == []
    assert plan(SUN, "19:00") == ["weekly_report"]
    assert plan(SUN, "08:00") == ["meal_0800"]                          # 1 meal + report = 2
    assert plan(SUN, "13:00", sent=["meal_0800"]) == []                 # last slot kept for the report


# ---------- texts ----------

def _seed(SessionLocal: sessionmaker[Session]) -> None:
    with SessionLocal.begin() as s:
        tools.add_exercise(s, "bench")
        tools.add_exercise(s, "squat")
        tools.log_workout(s, "bench 60x10,10,10 2026-10-23", today=TUE)


def test_workout_reminder_uses_day_plan_and_engine_targets(SessionLocal: sessionmaker[Session]) -> None:
    _seed(SessionLocal)
    with SessionLocal() as s:
        text = scheduler.workout_reminder_text(s, MON)
        assert "bench: 62.5 kg × 6, 6, 6 (increase_weight)" in text
        assert "squat: no history yet - tell me your starting weight" in text
        assert "🔥 1-day streak" in text                                 # Fri 23 completed
    with SessionLocal.begin() as s:
        tools.set_day_plan(s, "mon", ["squat"])
    with SessionLocal() as s:
        text = scheduler.workout_reminder_text(s, MON)
        assert "• squat:" in text and "• bench:" not in text


def test_workout_reminder_without_exercises(SessionLocal: sessionmaker[Session]) -> None:
    with SessionLocal() as s:
        assert "Add your exercises" in scheduler.workout_reminder_text(s, MON)


def test_missed_workout_text(SessionLocal: sessionmaker[Session]) -> None:
    _seed(SessionLocal)
    with SessionLocal() as s:
        assert "1-day streak is on the line" in scheduler.missed_workout_text(s, MON)
    with SessionLocal.begin() as s:
        tools.log_workout(s, "bench 62.5x6 2026-10-26", today=MON)
    with SessionLocal() as s:
        assert scheduler.missed_workout_text(s, MON) is None


@pytest.mark.parametrize("t, meal", [(dt.time(8), "Breakfast"), (dt.time(13), "Lunch"), (dt.time(20), "Dinner")])
def test_meal_reminder_text(t: dt.time, meal: str) -> None:
    assert scheduler.meal_reminder_text(t).startswith(f"🍽 {meal} time")


def test_describe() -> None:
    text = scheduler.describe(S, ["tue", "thu"], "18:30")
    assert "tue, thu at 18:30" in text and "max 2 messages a day" in text and "Sunday 19:00" in text


# ---------- tick: records what was sent, never repeats ----------

def test_tick_sends_once_and_respects_cap(SessionLocal: sessionmaker[Session]) -> None:
    _seed(SessionLocal)
    first = scheduler.tick(SessionLocal, S, at(MON, "07:00"))
    assert len(first) == 1 and first[0].startswith("🏋️ Workout day!")
    assert scheduler.tick(SessionLocal, S, at(MON, "07:01")) == []      # recorded - not sent again
    nudge = scheduler.tick(SessionLocal, S, at(MON, "21:00"))
    assert len(nudge) == 1 and nudge[0].startswith("⏰")
    assert scheduler.tick(SessionLocal, S, at(MON, "21:30")) == []
    with SessionLocal() as s:
        assert storage.notifications_on(s, MON) == ["workout_reminder", "missed_nudge"]


def test_tick_weekly_report(SessionLocal: sessionmaker[Session]) -> None:
    _seed(SessionLocal)
    [report] = scheduler.tick(SessionLocal, S, at(SUN, "19:00"), summarize=lambda p: "Solid week!")
    assert report.startswith("Solid week!") and "📅 Week 2026-10-26 to 2026-11-01" in report


def test_build_scheduler_registers_minute_check(SessionLocal: sessionmaker[Session]) -> None:
    sent: List[str] = []

    async def send(text: str) -> None:
        sent.append(text)

    sched = scheduler.build_scheduler(send, SessionLocal, S)
    [job] = sched.get_jobs()
    assert job.id == "consistency_check" and "interval[0:01:00]" in str(job.trigger)
    asyncio.run(job.func())                                             # runs without error at any real time
