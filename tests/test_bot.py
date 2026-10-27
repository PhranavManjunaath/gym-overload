"""Tests for bot.py - reply functions and handler wiring (no Telegram connection)."""
import datetime as dt
from pathlib import Path
from typing import Iterator

import pytest
from sqlalchemy.orm import Session, sessionmaker
from telegram.ext import CommandHandler, MessageHandler

import bot
import db as storage
import scheduler
import tools

TODAY = dt.date(2026, 10, 27)


@pytest.fixture
def SessionLocal(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    engine = storage.get_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    factory = storage.make_session_factory(engine)
    with factory.begin() as s:
        tools.add_exercise(s, "bench press")
        tools.log_workout(s, "bench press 60x10,10,10 2026-10-20", today=TODAY)
        tools.log_workout(s, "bench press 62.5x7,6,6 2026-10-23", today=TODAY)
    yield factory
    engine.dispose()


# ---------- split_message ----------

def test_short_message_is_one_part() -> None:
    assert bot.split_message("hello\nworld") == ["hello\nworld"]


def test_long_message_splits_on_lines() -> None:
    text = "\n".join(f"line {i:03d}" for i in range(100))   # 8 chars + newline each
    parts = bot.split_message(text, limit=100)
    assert all(len(p) <= 100 for p in parts)
    assert "\n".join(parts) == text


def test_very_long_single_line_is_cut() -> None:
    parts = bot.split_message("a" * 250, limit=100)
    assert [len(p) for p in parts] == [100, 100, 50]


def test_empty_message() -> None:
    assert bot.split_message("") == [""]


def test_plain_text_strips_markdown() -> None:
    assert bot.plain_text("Next: **62.5 kg** for `6` reps, rule __repeat__") == \
        "Next: 62.5 kg for 6 reps, rule repeat"
    assert bot.plain_text("60 kg × 10 * 3") == "60 kg × 10 * 3"     # single * left alone


# ---------- command replies ----------

def test_reply_next(SessionLocal: sessionmaker[Session]) -> None:
    text = bot.reply_next(SessionLocal, ["Bench", "Press"])
    assert text.startswith("Next bench press: 62.5 kg × 8, 7, 7")
    assert "Rule: add_reps" in text
    assert "2026-10-23: 62.5 kg × 7, 6, 6" in text


def test_reply_next_usage_and_unknown(SessionLocal: sessionmaker[Session]) -> None:
    assert bot.reply_next(SessionLocal, []).startswith("Usage")
    assert "isn't set up" in bot.reply_next(SessionLocal, ["squat"])


def test_reply_progress(SessionLocal: sessionmaker[Session]) -> None:
    text = bot.reply_progress(SessionLocal, ["bench", "press"])
    assert "2026-10-20: 60 kg, 30 reps, volume 1800 kg, e1RM 80 kg" in text
    assert bot.reply_progress(SessionLocal, []).startswith("Usage")


def test_reply_exercises(SessionLocal: sessionmaker[Session]) -> None:
    assert "bench press (barbell): 6-10 reps, 3 sets, +2.5 kg" in bot.reply_exercises(SessionLocal)


def test_help_mentions_log_format() -> None:
    assert "bench 60x10,10,9" in bot.HELP_TEXT and "/next" in bot.HELP_TEXT


# ---------- wiring ----------

def test_every_handler_is_locked_to_my_chat(SessionLocal: sessionmaker[Session]) -> None:
    app = bot.build_application("123456:TEST-token-not-real", 42, SessionLocal, coach=None,
                                settings=scheduler.ReminderSettings.from_env({}))
    handlers = app.handlers[0]
    commands = {c for h in handlers if isinstance(h, CommandHandler) for c in h.commands}
    assert commands == {"start", "help", "next", "progress", "exercises", "reminders"}
    for h in handlers[:-1]:
        assert repr(h.filters).startswith(("filters.Chat(42)", "<<filters.Chat(42) and")), h
    # the last handler only catches strangers (everyone except chat 42) and just logs them
    assert isinstance(handlers[-1], MessageHandler)
    assert repr(handlers[-1].filters) == "<inverted filters.Chat(42)>"
