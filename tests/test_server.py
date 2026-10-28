"""Tests for server.py - webhook + cron tick + website API in one service. Fake Telegram, no network."""
import asyncio
import datetime as dt
from pathlib import Path
from typing import Any, Iterator, List
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

import db as storage
import scheduler
import server
import tools

TZ = ZoneInfo("Asia/Kolkata")
MONDAY_7AM = dt.datetime(2026, 10, 26, 7, 0, tzinfo=TZ)


class FakeBot:
    def __init__(self) -> None:
        self.sent: List[str] = []
        self.webhook: dict = {}
        self.commands: list = []

    async def set_webhook(self, url: str, secret_token: str, allowed_updates: Any = None) -> None:
        self.webhook = {"url": url, "secret_token": secret_token}

    async def set_my_commands(self, commands: list) -> None:
        self.commands = commands

    async def send_message(self, chat_id: int, text: str) -> None:
        self.sent.append(text)


class FakeApplication:
    def __init__(self) -> None:
        self.bot = FakeBot()
        self.update_queue: asyncio.Queue = asyncio.Queue()
        self.events: List[str] = []

    async def initialize(self) -> None:
        self.events.append("initialize")

    async def start(self) -> None:
        self.events.append("start")

    async def stop(self) -> None:
        self.events.append("stop")

    async def shutdown(self) -> None:
        self.events.append("shutdown")


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "hook-secret")
    monkeypatch.setenv("CRON_SECRET", "cron-secret")
    monkeypatch.setenv("PUBLIC_URL", "https://gym.example.com/")
    monkeypatch.setenv("WEB_PASSWORD", "")
    for k in ["WORKOUT_DAYS", "WORKOUT_REMINDER_TIME", "RENDER_EXTERNAL_URL"]:
        monkeypatch.delenv(k, raising=False)


@pytest.fixture
def SessionLocal(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    engine = storage.get_engine(f"sqlite:///{(tmp_path / 'server.db').as_posix()}")
    factory = storage.make_session_factory(engine)
    with factory.begin() as s:
        tools.add_exercise(s, "bench")
        tools.log_workout(s, "bench 60x10,10,10 2026-10-23", today=dt.date(2026, 10, 26))
    yield factory
    engine.dispose()


def make(SessionLocal: sessionmaker[Session], now: dt.datetime = MONDAY_7AM):
    fake = FakeApplication()
    app = server.create_server(SessionLocal, fake, scheduler.ReminderSettings.from_env({}),
                               summarize=None, now=lambda: now)
    return app, fake


def test_startup_registers_webhook_and_shutdown_stops(env: None, SessionLocal: sessionmaker[Session]) -> None:
    app, fake = make(SessionLocal)
    with TestClient(app):
        assert fake.bot.webhook == {"url": "https://gym.example.com/telegram/webhook", "secret_token": "hook-secret"}
        assert fake.bot.commands                                  # / menu set
    assert fake.events == ["initialize", "start", "stop", "shutdown"]


def test_webhook_needs_the_secret(env: None, SessionLocal: sessionmaker[Session]) -> None:
    app, fake = make(SessionLocal)
    update = {"update_id": 1, "message": {"message_id": 1, "date": 0, "chat": {"id": 42, "type": "private"},
                                          "text": "/help"}}
    with TestClient(app) as c:
        assert c.post("/telegram/webhook", json=update).status_code == 403
        assert c.post("/telegram/webhook", json=update,
                      headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"}).status_code == 403
        assert fake.update_queue.empty()
        r = c.post("/telegram/webhook", json=update, headers={"X-Telegram-Bot-Api-Secret-Token": "hook-secret"})
        assert r.json() == {"ok": True}
        queued = fake.update_queue.get_nowait()
        assert queued.message.text == "/help" and queued.effective_chat.id == 42


def test_cron_tick_needs_the_key_and_sends_once(env: None, SessionLocal: sessionmaker[Session]) -> None:
    app, fake = make(SessionLocal)                                # Monday 07:00 = workout reminder due
    with TestClient(app) as c:
        assert c.get("/cron/tick").status_code == 403
        assert c.get("/cron/tick", headers={"X-Cron-Key": "nope"}).status_code == 403
        assert fake.bot.sent == []
        assert c.get("/cron/tick", headers={"X-Cron-Key": "cron-secret"}).json() == {"status": "ok", "sent": 1}
        assert fake.bot.sent[0].startswith("🏋️ Workout day!") and "62.5 kg × 6, 6, 6" in fake.bot.sent[0]
        assert c.get("/cron/tick", headers={"X-Cron-Key": "cron-secret"}).json()["sent"] == 0   # not repeated


def test_website_api_still_served(env: None, SessionLocal: sessionmaker[Session]) -> None:
    app, _ = make(SessionLocal)
    with TestClient(app) as c:
        assert c.get("/api/health").json() == {"status": "ok"}
        assert [e["exercise"] for e in c.get("/api/exercises").json()["exercises"]] == ["bench"]


def test_secrets_are_required(env: None, SessionLocal: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CRON_SECRET", "")
    with pytest.raises(RuntimeError, match="CRON_SECRET is missing"):
        make(SessionLocal)


def test_startup_lists_every_missing_setting_by_name(monkeypatch: pytest.MonkeyPatch) -> None:
    for n in server.REQUIRED:
        monkeypatch.delenv(n, raising=False)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "my-chat")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "has spaces+slash/")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_secret_value_that_must_not_be_printed")
    with pytest.raises(RuntimeError) as e:
        server.check_environment(full=True)
    msg = str(e.value)
    for n in ["TELEGRAM_BOT_TOKEN", "DATABASE_URL", "CRON_SECRET", "WEB_PASSWORD"]:
        assert f"{n} is missing" in msg
    assert "TELEGRAM_CHAT_ID must be a number" in msg and "only contain letters" in msg
    assert "gsk_secret_value" not in msg and "has spaces" not in msg          # names only, never values


def test_render_url_is_used_when_public_url_missing(env: None, SessionLocal: sessionmaker[Session],
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PUBLIC_URL")
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://gym-overload.onrender.com")
    app, fake = make(SessionLocal)
    with TestClient(app):
        assert fake.bot.webhook["url"] == "https://gym-overload.onrender.com/telegram/webhook"


def test_real_bot_handlers_answer_webhook_updates(env: None, SessionLocal: sessionmaker[Session]) -> None:
    """The real bot.build_application, fed through the webhook queue (no polling) - only the network is faked."""
    from telegram import User
    from telegram.ext import ExtBot

    import bot as bot_module

    sent: List[str] = []

    class OfflineBot(ExtBot):
        async def initialize(self) -> None:                      # skip get_me() over the network
            self._bot_user = User(id=1, first_name="coach", is_bot=True, username="coach_test_bot")
            self._initialized = True

        async def send_message(self, chat_id: Any, text: str, *args: Any, **kwargs: Any) -> None:
            sent.append(text)

        async def set_webhook(self, *args: Any, **kwargs: Any) -> bool:
            return True

        async def set_my_commands(self, *args: Any, **kwargs: Any) -> bool:
            return True

        async def shutdown(self) -> None:
            pass

    application = bot_module.build_application("123456:TEST-token-not-real", 42, SessionLocal, coach=None,
                                               settings=scheduler.ReminderSettings.from_env({}), webhook=True)
    assert application.updater is None                            # webhook mode: no polling
    application.bot = OfflineBot("123456:TEST-token-not-real")
    app = server.create_server(SessionLocal, application, scheduler.ReminderSettings.from_env({}),
                               now=lambda: MONDAY_7AM)
    update = {"update_id": 7, "message": {"message_id": 3, "date": 0, "chat": {"id": 42, "type": "private"},
                                          "from": {"id": 42, "is_bot": False, "first_name": "me"},
                                          "text": "/next bench", "entities": [{"type": "bot_command", "offset": 0,
                                                                              "length": 5}]}}
    with TestClient(app) as c:
        c.post("/telegram/webhook", json=update, headers={"X-Telegram-Bot-Api-Secret-Token": "hook-secret"})
        for _ in range(50):                                       # handlers run in the background
            if sent:
                break
            c.portal.call(asyncio.sleep, 0.05)
    assert sent and sent[0].startswith("Next bench: 62.5 kg × 6, 6, 6")
