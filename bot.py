"""
Telegram bot - the chat you use every day. Run: python bot.py

Only answers TELEGRAM_CHAT_ID (your own chat); everyone else is ignored.
    plain text            -> the coach (agent.py), e.g. "bench 60x10,10,9" or "what's next for squat?"
    /next <exercise>      -> next target, straight from the engine (no LLM)
    /progress <exercise>  -> last sessions: weight, reps, volume, e1RM (no LLM)
    /exercises, /reminders, /help
Reminders (scheduler.py) start with the bot.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Callable, List, Sequence

from dotenv import load_dotenv
from sqlalchemy.orm import Session, sessionmaker
from telegram import BotCommand, Update
from telegram.ext import Application, ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

import agent
import db as storage
import formatting
import parser as workout_parser
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
    "  /exercises - your exercises and settings\n"
    "  /reminders - when I'll remind you\n"
    "  /help - this message"
)

COMMANDS = [
    BotCommand("next", "Next target for an exercise"),
    BotCommand("progress", "Last sessions for an exercise"),
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


# ---------- wiring ----------

def build_application(token: str, chat_id: int, SessionLocal: sessionmaker[Session],
                      coach: agent.Coach, settings: scheduler.ReminderSettings) -> Application:
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

    async def on_stranger(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        log.warning("Ignored message from unknown chat %s", update.effective_chat.id if update.effective_chat else "?")

    async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        log.error("Unhandled error", exc_info=context.error)

    async def on_start(application: Application) -> None:
        await application.bot.set_my_commands(COMMANDS)
        sched = scheduler.build_scheduler(send, SessionLocal, settings)
        sched.start()
        application.bot_data["scheduler"] = sched
        log.info("Bot online. %s", scheduler.describe(settings).replace("\n", " "))

    async def on_stop(application: Application) -> None:
        sched = application.bot_data.get("scheduler")
        if sched:
            sched.shutdown(wait=False)

    app = ApplicationBuilder().token(token).post_init(on_start).post_shutdown(on_stop).build()
    app.add_handler(CommandHandler(["start", "help"], command(lambda a: HELP_TEXT), filters=me))
    app.add_handler(CommandHandler("next", command(lambda a: reply_next(SessionLocal, a)), filters=me))
    app.add_handler(CommandHandler("progress", command(lambda a: reply_progress(SessionLocal, a)), filters=me))
    app.add_handler(CommandHandler("exercises", command(lambda a: reply_exercises(SessionLocal)), filters=me))
    app.add_handler(CommandHandler("reminders", command(lambda a: scheduler.describe(settings)), filters=me))
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
    coach = agent.create_coach(SessionLocal)

    build_application(token, int(chat_id), SessionLocal, coach, settings).run_polling(
        allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
