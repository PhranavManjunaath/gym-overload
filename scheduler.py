"""
Scheduler - workout and meal reminders for consistency (APScheduler).

Settings come from .env (defaults in brackets):
    REMINDER_TIMEZONE           [Asia/Kolkata]
    WORKOUT_DAYS                [mon,wed,fri]
    WORKOUT_REMINDER_TIME       [07:00]   - today's targets, straight from the engine
    MISSED_WORKOUT_CHECK_TIME   [21:00]   - nudge only if nothing was logged today
    MEAL_REMINDER_TIMES         [08:00,13:00,20:00]  (empty = no meal reminders)

Reminder texts are built in plain Python - no LLM, so the targets are exact.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import os
from dataclasses import dataclass, field
from typing import Awaitable, Callable, List, Mapping, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session, sessionmaker

import db as storage
import formatting
import tools

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
Send = Callable[[str], Awaitable[None]]


@dataclass
class ReminderSettings:
    timezone: str = "Asia/Kolkata"
    workout_days: List[str] = field(default_factory=lambda: ["mon", "wed", "fri"])
    workout_time: dt.time = dt.time(7, 0)
    missed_check_time: dt.time = dt.time(21, 0)
    meal_times: List[dt.time] = field(default_factory=lambda: [dt.time(8), dt.time(13), dt.time(20)])

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "ReminderSettings":
        env = os.environ if env is None else env
        d = cls()
        s = cls(
            timezone=env.get("REMINDER_TIMEZONE", d.timezone).strip(),
            workout_days=_parse_days(env.get("WORKOUT_DAYS", ",".join(d.workout_days))),
            workout_time=_parse_time(env.get("WORKOUT_REMINDER_TIME", "07:00")),
            missed_check_time=_parse_time(env.get("MISSED_WORKOUT_CHECK_TIME", "21:00")),
            meal_times=[_parse_time(t) for t in env.get("MEAL_REMINDER_TIMES", "08:00,13:00,20:00").split(",")
                        if t.strip()],
        )
        try:
            ZoneInfo(s.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"Unknown REMINDER_TIMEZONE '{s.timezone}' (e.g. Asia/Kolkata).") from None
        return s


def _parse_time(text: str) -> dt.time:
    try:
        return dt.datetime.strptime(text.strip(), "%H:%M").time()
    except ValueError:
        raise ValueError(f"Bad time '{text}' - use 24h HH:MM, e.g. 07:30.") from None


def _parse_days(text: str) -> List[str]:
    days = [d.strip().lower()[:3] for d in text.split(",") if d.strip()]
    bad = [d for d in days if d not in DAYS]
    if bad or not days:
        raise ValueError(f"Bad WORKOUT_DAYS '{text}' - use e.g. mon,wed,fri.")
    return sorted(set(days), key=DAYS.index)


# ---------- reminder texts ----------

def workout_reminder_text(session: Session) -> str:
    exercises = tools.list_exercises(session)["exercises"]
    if not exercises:
        return "🏋️ Workout day! Add your exercises first, e.g. 'add bench press, barbell'."
    lines = ["🏋️ Workout day! Today's targets:"]
    for e in exercises:
        r = tools.recommend_next(session, e["exercise"])
        if r["status"] == "ok":
            lines.append(f"  • {e['exercise']}: {formatting.format_targets(r['next'])} ({r['rule']})")
        else:
            lines.append(f"  • {e['exercise']}: no history yet - tell me your starting weight")
    lines.append("Log it after, e.g. 'bench 60x10,10,9'.")
    return "\n".join(lines)


def missed_workout_text(session: Session, today: dt.date) -> Optional[str]:
    if storage.count_sessions_on(session, today) > 0:
        return None
    return "⏰ No workout logged today. Did you train? Send it now, e.g. 'bench 60x10,10,9'."


def meal_reminder_text(t: dt.time) -> str:
    meal = "breakfast" if t.hour < 11 else "lunch" if t.hour < 16 else "dinner"
    return f"🍽 {meal.capitalize()} time - eat a protein-rich meal and drink some water."


def describe(s: ReminderSettings) -> str:
    hm = lambda t: t.strftime("%H:%M")
    meals = ", ".join(hm(t) for t in s.meal_times) or "off"
    return (f"Reminders ({s.timezone}):\n"
            f"  • Workout days: {', '.join(s.workout_days)} at {hm(s.workout_time)}\n"
            f"  • Missed-workout check: {hm(s.missed_check_time)} on workout days\n"
            f"  • Meals: {meals}\n"
            "Change them in .env and restart the bot.")


# ---------- scheduler ----------

def build_scheduler(send: Send, SessionLocal: sessionmaker[Session], settings: ReminderSettings) -> AsyncIOScheduler:
    """Scheduler with all reminder jobs added (not started - call .start() inside the event loop)."""
    tz = ZoneInfo(settings.timezone)
    days = ",".join(settings.workout_days)

    def with_session(fn: Callable[[Session], Optional[str]]) -> Optional[str]:
        with SessionLocal() as s:
            return fn(s)

    async def workout_job() -> None:
        await send(await asyncio.to_thread(with_session, workout_reminder_text))

    async def missed_job() -> None:
        today = dt.datetime.now(tz).date()
        text = await asyncio.to_thread(with_session, lambda s: missed_workout_text(s, today))
        if text:
            await send(text)

    def meal_job(t: dt.time) -> Callable[[], Awaitable[None]]:
        async def job() -> None:
            await send(meal_reminder_text(t))
        return job

    sched = AsyncIOScheduler(timezone=tz)
    sched.add_job(workout_job, CronTrigger(day_of_week=days, hour=settings.workout_time.hour,
                                           minute=settings.workout_time.minute, timezone=tz),
                  id="workout_reminder", misfire_grace_time=600)
    sched.add_job(missed_job, CronTrigger(day_of_week=days, hour=settings.missed_check_time.hour,
                                          minute=settings.missed_check_time.minute, timezone=tz),
                  id="missed_workout_check", misfire_grace_time=600)
    for t in settings.meal_times:
        sched.add_job(meal_job(t), CronTrigger(hour=t.hour, minute=t.minute, timezone=tz),
                      id=f"meal_{t.strftime('%H%M')}", misfire_grace_time=600)
    return sched
