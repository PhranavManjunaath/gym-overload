"""
Telegram bot - the chat you use every day. Run: python bot.py

Only answers TELEGRAM_CHAT_ID (your own chat); everyone else is ignored.
    plain text            -> the coach (agent.py), e.g. "bench 60x10,10,9" or "what's next for squat?"
    /next <exercise>      -> next target, straight from the engine (no LLM)
    /progress <exercise>  -> last sessions: weight, reps, volume, e1RM (no LLM)
    /meal, /fixmeal, /setprotein, /protein, /streak, /schedule, /plan, /goal, /report, /export
    /exercises, /reminders, /help
Reminders (scheduler.py, max 2 a day) start with the bot.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import io
import logging
import os
import re
from typing import Any, Callable, Dict, List, Optional, Sequence

from dotenv import load_dotenv
from sqlalchemy.orm import Session, sessionmaker
from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (Application, ApplicationBuilder, CallbackQueryHandler, CommandHandler, ContextTypes,
                          MessageHandler, filters)

import agent
import db as storage
import formatting
import parser as workout_parser
import reports
import scheduler
import tools

log = logging.getLogger("gym_bot")
TELEGRAM_LIMIT = 4000   # Telegram's hard limit is 4096 characters per message

HELP_TEXT = (
    "I'm your progressive-overload coach. Every number I give comes from tested Python, "
    "and I always show what it was based on.\n\n"
    "Log a workout by just sending it:\n" + workout_parser.HELP + "\n\n"
    "Or ask in your own words: \"what's next for bench?\", \"add squat, barbell\", \"how's my deadlift going?\"\n\n"
    "Commands:\n"
    "  /next <exercise> - next target with the rule and data behind it\n"
    "  /progress <exercise> - your last sessions\n"
    "  /streak - training streak and consistency\n"
    "  /meal <text> - log a meal, e.g. /meal chicken 200g, 2 eggs (protein is estimated)\n"
    "  /fixmeal <id> <grams> - correct a meal's protein\n"
    "  /setprotein <grams> - your daily protein target\n"
    "  /protein - today's protein vs your target\n"
    "  /schedule [days] [HH:MM] - e.g. /schedule mon,wed,fri 07:30\n"
    "  /plan <day> <exercises> - e.g. /plan mon bench press, squat\n"
    "  /goal <text> - your training goal\n"
    "  /report - this week's report\n"
    "  /export - your data as CSV\n"
    "  /resetday [yesterday|2026-10-26] - delete one day's logs (asks first)\n"
    "  /reset - delete everything and start fresh (asks first)\n"
    "  /exercises - your exercises and settings\n"
    "  /reminders - when I'll remind you (max 2 messages a day)\n"
    "  /help - this message"
)

COMMANDS = [
    BotCommand("next", "Next target for an exercise"),
    BotCommand("progress", "Last sessions for an exercise"),
    BotCommand("streak", "Training streak"),
    BotCommand("meal", "Log a meal"),
    BotCommand("protein", "Today's protein"),
    BotCommand("report", "This week's report"),
    BotCommand("schedule", "Training days and reminder time"),
    BotCommand("plan", "Exercises for a weekday"),
    BotCommand("export", "Download your data (CSV)"),
    BotCommand("resetday", "Delete a day's logs (asks first)"),
    BotCommand("reset", "Delete everything (asks first)"),
    BotCommand("exercises", "Your exercises"),
    BotCommand("reminders", "Reminder schedule"),
    BotCommand("help", "How to use the coach"),
]


# ---------- replies (plain functions, easy to test) ----------

def split_message(text: str, limit: int = TELEGRAM_LIMIT) -> List[str]:
    """Split on line breaks so each part fits in one Telegram message."""
    parts: List[str] = []
    current = ""
    for line in text.split("\n"):
        while len(line) > limit:                       # a single very long line
            if current:
                parts.append(current)
                current = ""
            parts.append(line[:limit])
            line = line[limit:]
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit:
            parts.append(current)
            current = line
        else:
            current = candidate
    if current or not parts:
        parts.append(current)
    return parts


def plain_text(text: str) -> str:
    """Drop markdown markers the LLM sometimes adds; Telegram would show them as literal symbols."""
    return re.sub(r"\*\*|__|`", "", text)


def reply_next(SessionLocal: sessionmaker[Session], args: Sequence[str]) -> str:
    exercise = " ".join(args).strip()
    if not exercise:
        return "Usage: /next <exercise>, e.g. /next bench press"
    with SessionLocal() as s:
        return formatting.format_recommendation(tools.recommend_next(s, exercise))


def reply_progress(SessionLocal: sessionmaker[Session], args: Sequence[str]) -> str:
    exercise = " ".join(args).strip()
    if not exercise:
        return "Usage: /progress <exercise>, e.g. /progress squat"
    with SessionLocal() as s:
        return formatting.format_progress(tools.get_progress(s, exercise, last_n=5))


def reply_exercises(SessionLocal: sessionmaker[Session]) -> str:
    with SessionLocal() as s:
        return formatting.format_exercises(tools.list_exercises(s))


def _run(SessionLocal: sessionmaker[Session], fn: Callable[..., Dict[str, Any]], **kwargs: Any) -> Dict[str, Any]:
    """One tool call = one transaction: commit on success, roll back otherwise."""
    with SessionLocal() as s:
        r = fn(s, **kwargs)
        if r.get("status") == "ok":
            s.commit()
        else:
            s.rollback()
        return r


def _number(text: str) -> Optional[float]:
    try:
        return float(text.lower().removesuffix("g"))
    except ValueError:
        return None


def reply_meal(SessionLocal: sessionmaker[Session], args: Sequence[str], today: Optional[dt.date] = None) -> str:
    text = " ".join(args).strip()
    if not text:
        return "Usage: /meal <what you ate>, e.g. /meal chicken breast 200g, 2 eggs (or add '35g protein')"
    r = _run(SessionLocal, tools.log_meal, text=text, today=today)
    out = formatting.format_meal(r)
    if r.get("status") == "ok" and r["meal"]["protein_g"] is None:
        out += f"\nFix it with /fixmeal {r['meal']['id']} <grams>"
    elif r.get("status") == "ok" and r["meal"]["protein_estimated"]:
        out += f"\nWrong? /fixmeal {r['meal']['id']} <grams>"
    return out


def reply_fixmeal(SessionLocal: sessionmaker[Session], args: Sequence[str]) -> str:
    if len(args) != 2 or not args[0].isdigit() or _number(args[1]) is None:
        return "Usage: /fixmeal <meal id> <grams>, e.g. /fixmeal 12 35"
    r = _run(SessionLocal, tools.correct_meal_protein, meal_id=int(args[0]), protein_g=_number(args[1]))
    if r["status"] != "ok":
        return r["message"]
    return f"Meal {r['meal']['id']} updated to {r['meal']['protein_g']:g} g (your number).\n" + \
        formatting.format_protein_day(r["day"])


def reply_setprotein(SessionLocal: sessionmaker[Session], args: Sequence[str]) -> str:
    grams = _number(args[0]) if len(args) == 1 else None
    if grams is None:
        return "Usage: /setprotein <grams per day>, e.g. /setprotein 140"
    r = _run(SessionLocal, tools.set_protein_target, grams=grams)
    return f"Protein target set to {r['target_g']:g} g a day." if r["status"] == "ok" else r["message"]


def reply_protein(SessionLocal: sessionmaker[Session], today: Optional[dt.date] = None) -> str:
    r = _run(SessionLocal, tools.protein_day, day=today)
    lines = [formatting.format_protein_day(r)]
    for m in r["meals"]:
        p = "?" if m["protein_g"] is None else f"{m['protein_g']:g} g" + (" est." if m["protein_estimated"] else "")
        lines.append(f"  • [{m['id']}] {m['text']}: {p}")
    if not r["target_g"]:
        lines.append("Set your own target with /setprotein <grams>.")
    return "\n".join(lines)


def reply_streak(SessionLocal: sessionmaker[Session], today: Optional[dt.date] = None) -> str:
    return formatting.format_streak(_run(SessionLocal, tools.streak, today=today))


def reply_schedule(SessionLocal: sessionmaker[Session], args: Sequence[str]) -> str:
    days = next((a for a in args if ":" not in a), None)
    time = next((a for a in args if ":" in a), None)
    if days is None and time is None:
        r = _run(SessionLocal, tools.get_schedule)
    else:
        r = _run(SessionLocal, tools.set_schedule, training_days=days, workout_time=time)
        if r["status"] != "ok":
            return r["message"] + "\nUsage: /schedule mon,wed,fri 07:30"
    plan = "".join(f"\n  • {d}: {', '.join(n)}" for d, n in r["day_plan"].items())
    return (f"Training days: {', '.join(r['training_days'])} · reminder {r['workout_time']}"
            + (f"\nPlan:{plan}" if plan else "\nNo per-day plan yet - /plan mon bench press, squat"))


def reply_plan(SessionLocal: sessionmaker[Session], args: Sequence[str]) -> str:
    if len(args) < 2:
        return "Usage: /plan <day> <exercises>, e.g. /plan mon bench press, squat"
    names = [n.strip() for n in " ".join(args[1:]).split(",") if n.strip()]
    r = _run(SessionLocal, tools.set_day_plan, day=args[0], exercises=names)
    return f"{r['day']}: {', '.join(r['exercises'])}" if r["status"] == "ok" else r["message"]


def reply_goal(SessionLocal: sessionmaker[Session], args: Sequence[str]) -> str:
    if not args:
        with SessionLocal() as s:
            return f"Goal: {storage.get_setting(s, 'goal') or 'not set'} - change it with /goal <text>"
    r = _run(SessionLocal, tools.set_goal, goal=" ".join(args))
    return f"Goal saved: {r['goal']}" if r["status"] == "ok" else r["message"]


def reply_report(SessionLocal: sessionmaker[Session], summarize: Optional[reports.Summarize] = None,
                 today: Optional[dt.date] = None) -> str:
    with SessionLocal() as s:
        return reports.weekly_report(s, today or dt.date.today(), summarize)


def parse_day(args: Sequence[str], today: dt.date) -> Optional[dt.date]:
    """No argument = today; also 'yesterday' or 2026-10-26. Future dates are refused."""
    if not args:
        return today
    word = args[0].strip().lower()
    if word == "today":
        return today
    if word == "yesterday":
        return today - dt.timedelta(days=1)
    try:
        d = dt.date.fromisoformat(word)
    except ValueError:
        return None
    return d if d <= today else None


def resetday_preview(SessionLocal: sessionmaker[Session], args: Sequence[str],
                     today: Optional[dt.date] = None) -> tuple:
    """(message, day to delete or None). Lists exactly what would be deleted."""
    day = parse_day(args, today or dt.date.today())
    if day is None:
        return "Usage: /resetday, /resetday yesterday or /resetday 2026-10-26", None
    with SessionLocal() as s:
        r = tools.day_summary(s, day)
    if not r["workouts"] and not r["meals"]:
        return f"Nothing is logged on {day.isoformat()}.", None
    lines = [f"Delete everything logged on {day.isoformat()}?"]
    lines += [f"  • {w['exercise']}: {formatting.format_sets(w['sets'])}" for w in r["workouts"]]
    lines += [f"  • meal: {m['text']}" for m in r["meals"]]
    lines.append("You can log it again afterwards.")
    return "\n".join(lines), day


def reset_preview(SessionLocal: sessionmaker[Session]) -> tuple:
    """(message, True if there is anything to delete)."""
    with SessionLocal() as s:
        n_ex = len(storage.list_exercises(s))
        n_days = len(storage.session_dates(s))
        n_meals = len(storage.all_meals(s))
    if not (n_ex or n_days or n_meals):
        return "There's nothing to reset - your data is already empty.", False
    return (f"⚠️ Delete EVERYTHING? {n_ex} exercises, workouts on {n_days} days, {n_meals} meals, "
            f"plus your goal, schedule, plan and preferences.\nThis can't be undone - "
            f"use /export first if you want a copy."), True


def do_resetday(SessionLocal: sessionmaker[Session], day: dt.date) -> str:
    r = _run(SessionLocal, tools.reset_day, day=day)
    d = r["deleted"]
    return f"🗑 Deleted {d['sessions']} workout(s) and {d['meals']} meal(s) from {r['date']}. Log it again whenever you're ready."


def do_reset(SessionLocal: sessionmaker[Session]) -> str:
    _run(SessionLocal, tools.reset_all)
    return "🗑 Everything was deleted. Fresh start: add an exercise, e.g. 'add bench press, barbell'."


def export_files(SessionLocal: sessionmaker[Session]) -> List[tuple]:
    with SessionLocal() as s:
        return [("workouts.csv", reports.export_workouts_csv(s)), ("meals.csv", reports.export_meals_csv(s))]


# ---------- wiring ----------

def build_application(token: str, chat_id: int, SessionLocal: sessionmaker[Session],
                      coach: agent.Coach, settings: scheduler.ReminderSettings,
                      summarize: Optional[reports.Summarize] = None, webhook: bool = False) -> Application:
    """webhook=True: no polling updater - updates arrive via server.py's /telegram/webhook instead."""
    me = filters.Chat(chat_id=chat_id)

    async def send(text: str) -> None:
        for part in split_message(text):
            await app.bot.send_message(chat_id=chat_id, text=part)

    async def answer(update: Update, text: str) -> None:
        for part in split_message(text):
            await update.effective_message.reply_text(part)

    def command(fn: Callable[[Sequence[str]], str]) -> Callable:
        async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            await answer(update, await asyncio.to_thread(fn, context.args or []))
        return handler

    async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.effective_chat.send_action("typing")
        try:
            reply = plain_text(await asyncio.to_thread(coach.chat, chat_id, update.effective_message.text))
        except Exception:
            log.exception("coach failed")
            reply = ("The AI coach is unavailable right now. Nothing was lost - "
                     "/next and /progress still work without it.")
        await answer(update, reply)

    async def on_export(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        for name, content in await asyncio.to_thread(export_files, SessionLocal):
            await update.effective_message.reply_document(document=io.BytesIO(content.encode("utf-8")), filename=name)

    def buttons(yes_label: str, yes_data: str) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([[InlineKeyboardButton(yes_label, callback_data=yes_data),
                                      InlineKeyboardButton("Cancel", callback_data="cancel")]])

    async def on_resetday(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        text, day = await asyncio.to_thread(resetday_preview, SessionLocal, context.args or [])
        markup = buttons("Yes, delete", f"resetday:{day.isoformat()}") if day else None
        await update.effective_message.reply_text(text, reply_markup=markup)

    async def on_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        text, has_data = await asyncio.to_thread(reset_preview, SessionLocal)
        markup = buttons("Yes, delete everything", "resetall") if has_data else None
        await update.effective_message.reply_text(text, reply_markup=markup)

    async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if update.effective_chat is None or update.effective_chat.id != chat_id:
            return                                            # only you can confirm a delete
        await query.answer()
        data = query.data or ""
        if data.startswith("resetday:"):
            result = await asyncio.to_thread(do_resetday, SessionLocal, dt.date.fromisoformat(data.split(":", 1)[1]))
        elif data == "resetall":
            result = await asyncio.to_thread(do_reset, SessionLocal)
        else:
            await query.edit_message_text("Cancelled - nothing was deleted.")
            return
        if coach is not None:
            coach.forget(chat_id)                             # so old logs don't block re-logging
        await query.edit_message_text(result)

    def reminders_text() -> str:
        sched = _run(SessionLocal, tools.get_schedule)
        return scheduler.describe(settings, sched["training_days"], sched["workout_time"])

    async def on_stranger(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        log.warning("Ignored message from unknown chat %s", update.effective_chat.id if update.effective_chat else "?")

    async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        log.error("Unhandled error", exc_info=context.error)

    async def on_start(application: Application) -> None:
        await application.bot.set_my_commands(COMMANDS)
        sched = scheduler.build_scheduler(send, SessionLocal, settings, summarize)
        sched.start()
        application.bot_data["scheduler"] = sched
        log.info("Bot online. %s", reminders_text().replace("\n", " "))

    async def on_stop(application: Application) -> None:
        sched = application.bot_data.get("scheduler")
        if sched:
            sched.shutdown(wait=False)

    builder = ApplicationBuilder().token(token).post_init(on_start).post_shutdown(on_stop)
    if webhook:
        builder = builder.updater(None)
    app = builder.build()
    app.add_handler(CommandHandler(["start", "help"], command(lambda a: HELP_TEXT), filters=me))
    app.add_handler(CommandHandler("next", command(lambda a: reply_next(SessionLocal, a)), filters=me))
    app.add_handler(CommandHandler("progress", command(lambda a: reply_progress(SessionLocal, a)), filters=me))
    app.add_handler(CommandHandler("exercises", command(lambda a: reply_exercises(SessionLocal)), filters=me))
    app.add_handler(CommandHandler("reminders", command(lambda a: reminders_text()), filters=me))
    app.add_handler(CommandHandler("meal", command(lambda a: reply_meal(SessionLocal, a)), filters=me))
    app.add_handler(CommandHandler("fixmeal", command(lambda a: reply_fixmeal(SessionLocal, a)), filters=me))
    app.add_handler(CommandHandler("setprotein", command(lambda a: reply_setprotein(SessionLocal, a)), filters=me))
    app.add_handler(CommandHandler("protein", command(lambda a: reply_protein(SessionLocal)), filters=me))
    app.add_handler(CommandHandler("streak", command(lambda a: reply_streak(SessionLocal)), filters=me))
    app.add_handler(CommandHandler("schedule", command(lambda a: reply_schedule(SessionLocal, a)), filters=me))
    app.add_handler(CommandHandler("plan", command(lambda a: reply_plan(SessionLocal, a)), filters=me))
    app.add_handler(CommandHandler("goal", command(lambda a: reply_goal(SessionLocal, a)), filters=me))
    app.add_handler(CommandHandler("report", command(lambda a: reply_report(SessionLocal, summarize)), filters=me))
    app.add_handler(CommandHandler("export", on_export, filters=me))
    app.add_handler(CommandHandler("resetday", on_resetday, filters=me))
    app.add_handler(CommandHandler("reset", on_reset, filters=me))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(me & filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(MessageHandler(~me, on_stranger))
    app.add_error_handler(on_error)
    return app


def main() -> None:
    logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
    # httpx logs every request URL, and Telegram URLs contain the bot token - keep it out of logs.
    logging.getLogger("httpx").setLevel(logging.WARNING)

    load_dotenv(storage.PROJECT_DIR / ".env")
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id.lstrip("-").isdigit():
        raise SystemExit("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID (a number) in .env")

    settings = scheduler.ReminderSettings.from_env()
    engine = storage.get_engine()
    log.info("Database: %s", storage.describe_engine(engine))
    SessionLocal = storage.make_session_factory(engine)
    llm = agent.build_llm()
    coach = agent.Coach(llm, SessionLocal)
    summarize = lambda prompt: str(llm.invoke(prompt).content)     # checked by reports.summarize_checked

    build_application(token, int(chat_id), SessionLocal, coach, settings, summarize).run_polling(
        allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
