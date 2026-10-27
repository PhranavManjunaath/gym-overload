"""
Scheduler - consistency messages (APScheduler), at most 2 per day.

One job runs every minute and asks plan_messages() what is due. plan_messages is a
pure function of (time, schedule, what was already sent today, whether you trained),
so every rule is testable with fake dates:

    workout_reminder  training day, at your reminder time, until the nudge time,
                      skipped if you already logged today - includes today's targets
                      from recommend_next and your streak
    missed_nudge      training day, nothing logged by the nudge time (21:00) - once
    weekly_report     Sunday at WEEKLY_REPORT_TIME (19:00) - numbers from Python
    meal_HHMM         meal reminders, lowest priority, only within an hour of their time,
                      and only if they don't use up a slot a workout message may still need

Training days and reminder time come from the app (/schedule) and fall back to .env:
    REMINDER_TIMEZONE [Asia/Kolkata]   WORKOUT_DAYS [mon,wed,fri]   WORKOUT_REMINDER_TIME [07:00]
    MISSED_WORKOUT_CHECK_TIME [21:00]  WEEKLY_REPORT_TIME [19:00]   MEAL_REMINDER_TIMES [08:00,13:00,20:00]
Messages are sent by the Telegram bot and recorded, so a restart never sends twice.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import os
from dataclasses import dataclass, field
from typing import Awaitable, Callable, List, Mapping, Optional, Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.orm import Session, sessionmaker

import analytics
import db as storage
import formatting
import reports
import tools

DAYS = analytics.WEEKDAYS
DAILY_CAP = 2
MEAL_WINDOW = dt.timedelta(hours=1)
Send = Callable[[str], Awaitable[None]]


@dataclass
class ReminderSettings:
    timezone: str = "Asia/Kolkata"
    workout_days: List[str] = field(default_factory=lambda: ["mon", "wed", "fri"])
    workout_time: dt.time = dt.time(7, 0)
    missed_check_time: dt.time = dt.time(21, 0)
    meal_times: List[dt.time] = field(default_factory=lambda: [dt.time(8), dt.time(13), dt.time(20)])
    weekly_report_time: dt.time = dt.time(19, 0)

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
            weekly_report_time=_parse_time(env.get("WEEKLY_REPORT_TIME", "19:00")),
        )
        try:
            ZoneInfo(s.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"Unknown REMINDER_TIMEZONE '{s.timezone}' (e.g. Asia/Kolkata).") from None
        return s


def _parse_time(text: str) -> dt.time:
    return analytics.parse_time(text)


def _parse_days(text: str) -> List[str]:
    try:
        return analytics.parse_days(text)
    except ValueError:
        raise ValueError(f"Bad WORKOUT_DAYS '{text}' - use e.g. mon,wed,fri.") from None


# ---------- what is due (pure, testable) ----------

def plan_messages(now: dt.datetime, training_days: Sequence[str], workout_time: dt.time,
                  settings: ReminderSettings, sent_today: Sequence[str], logged_today: bool) -> List[str]:
    """Kinds of message to send right now, in order, never exceeding DAILY_CAP per day."""
    t, today = now.time(), now.date()
    training = analytics.is_training_day(today, training_days)
    sunday = today.weekday() == 6
    sent = list(sent_today)
    budget = DAILY_CAP - len(sent)
    if budget <= 0:
        return []

    due_important = []
    if training and not logged_today and "workout_reminder" not in sent \
            and workout_time <= t < settings.missed_check_time:
        due_important.append("workout_reminder")
    if sunday and "weekly_report" not in sent and t >= settings.weekly_report_time:
        due_important.append("weekly_report")
    if training and not logged_today and "missed_nudge" not in sent and t >= settings.missed_check_time:
        due_important.append("missed_nudge")
    out = due_important[:budget]
    budget -= len(out)

    # Important messages that could still come later today keep their slot.
    later = 0
    if training and not logged_today and "workout_reminder" not in sent + out and t < workout_time:
        later += 1
    if training and not logged_today and "missed_nudge" not in sent + out and t < settings.missed_check_time:
        later += 1
    if sunday and "weekly_report" not in sent + out and t < settings.weekly_report_time:
        later += 1

    for mt in settings.meal_times:
        kind = f"meal_{mt.strftime('%H%M')}"
        start = dt.datetime.combine(today, mt, tzinfo=now.tzinfo)
        if kind not in sent and start <= now < start + MEAL_WINDOW and budget - later > 0:
            out.append(kind)
            budget -= 1
    return out


# ---------- message texts ----------

def workout_reminder_text(session: Session, today: Optional[dt.date] = None) -> str:
    today = today or dt.date.today()
    sched = tools.get_schedule(session)
    planned = sched["day_plan"].get(analytics.weekday(today))
    exercises = planned or [e["exercise"] for e in tools.list_exercises(session)["exercises"]]
    if not exercises:
        return "🏋️ Workout day! Add your exercises first, e.g. 'add bench press, barbell'."
    lines = ["🏋️ Workout day! Today's targets:"]
    for name in exercises:
        r = tools.recommend_next(session, name)
        if r["status"] == "ok":
            lines.append(f"  • {name}: {formatting.format_targets(r['next'])} ({r['rule']})")
        else:
            lines.append(f"  • {name}: no history yet - tell me your starting weight")
    st = tools.streak(session, today)
    if st["current_streak"]:
        lines.append(f"🔥 {st['current_streak']}-day streak - keep it going!")
    lines.append("Log it after, e.g. 'bench 60x10,10,9'.")
    return "\n".join(lines)


def missed_workout_text(session: Session, today: dt.date) -> Optional[str]:
    if storage.count_sessions_on(session, today) > 0:
        return None
    st = tools.streak(session, today)
    keep = f" Your {st['current_streak']}-day streak is on the line." if st["current_streak"] else ""
    return f"⏰ No workout logged today.{keep} Trained? Send it now, e.g. 'bench 60x10,10,9'."


def meal_reminder_text(t: dt.time) -> str:
    meal = "breakfast" if t.hour < 11 else "lunch" if t.hour < 16 else "dinner"
    return f"🍽 {meal.capitalize()} time - eat a protein-rich meal and drink some water."


def describe(s: ReminderSettings, training_days: Optional[Sequence[str]] = None,
             workout_time: Optional[str] = None) -> str:
    hm = lambda t: t.strftime("%H:%M")
    days = ", ".join(training_days if training_days is not None else s.workout_days)
    meals = ", ".join(hm(t) for t in s.meal_times) or "off"
    return (f"Reminders ({s.timezone}), max {DAILY_CAP} messages a day:\n"
            f"  • Workout days: {days} at {workout_time or hm(s.workout_time)}\n"
            f"  • Missed-workout check: {hm(s.missed_check_time)} on workout days\n"
            f"  • Weekly report: Sunday {hm(s.weekly_report_time)}\n"
            f"  • Meals: {meals} (only if a slot is free)\n"
            "Change days/time with /schedule; the rest in .env (restart the bot).")


def message_text(session: Session, kind: str, today: dt.date,
                 summarize: Optional[reports.Summarize] = None) -> Optional[str]:
    if kind == "workout_reminder":
        return workout_reminder_text(session, today)
    if kind == "missed_nudge":
        return missed_workout_text(session, today)
    if kind == "weekly_report":
        return reports.weekly_report(session, today, summarize)
    if kind.startswith("meal_"):
        return meal_reminder_text(dt.datetime.strptime(kind[5:], "%H%M").time())
    return None


# ---------- scheduler ----------

def tick(SessionLocal: sessionmaker[Session], settings: ReminderSettings, now: dt.datetime,
         summarize: Optional[reports.Summarize] = None) -> List[str]:
    """Decide and build what's due now; records each message as sent. Returns the texts."""
    today = now.date()
    with SessionLocal() as s:
        sched = tools.get_schedule(s)
        kinds = plan_messages(now, sched["training_days"], analytics.parse_time(sched["workout_time"]), settings,
                              storage.notifications_on(s, today), storage.count_sessions_on(s, today) > 0)
        texts = []
        for kind in kinds:
            text = message_text(s, kind, today, summarize)
            storage.record_notification(s, today, kind)          # recorded even if skipped: never retried
            if text:
                texts.append(text)
        s.commit()
    return texts


def build_scheduler(send: Send, SessionLocal: sessionmaker[Session], settings: ReminderSettings,
                    summarize: Optional[reports.Summarize] = None) -> AsyncIOScheduler:
    """Scheduler with the every-minute check (not started - call .start() inside the event loop)."""
    tz = ZoneInfo(settings.timezone)

    async def check() -> None:
        texts = await asyncio.to_thread(tick, SessionLocal, settings, dt.datetime.now(tz), summarize)
        for text in texts:
            await send(text)

    sched = AsyncIOScheduler(timezone=tz)
    sched.add_job(check, IntervalTrigger(minutes=1, timezone=tz), id="consistency_check",
                  max_instances=1, coalesce=True, misfire_grace_time=60)
    return sched
