"""
Server - everything in ONE free web service (e.g. Render's free plan, no card needed).

    /api/...           the website API (api.py, unchanged)
    /telegram/webhook  Telegram pushes your messages here (webhook mode) - same handlers as bot.py
    /cron/tick         a free external cron (e.g. cron-job.org) calls this every 5 minutes:
                       it runs the reminder check (scheduler.tick, max 2 messages a day) and the
                       pings keep the free service from going to sleep

Run: uvicorn server:create_server --factory --host 0.0.0.0 --port $PORT

Env (on top of the usual ones in .env.example):
    TELEGRAM_WEBHOOK_SECRET  random string; Telegram sends it back on every update so strangers
                             can't post fake updates (letters, digits, _ and - only)
    CRON_SECRET              random string the cron sends in the X-Cron-Key header
    PUBLIC_URL               https address of this service (Render sets RENDER_EXTERNAL_URL itself)

Locally, keep using `python bot.py` (polling). Note: starting bot.py removes the webhook, so the
cloud bot stops hearing you until the cloud service restarts (it re-registers on startup).
"""
from __future__ import annotations

import asyncio
import datetime as dt
import hmac
import logging
import os
import re
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Callable, Optional
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Header, HTTPException, Request
from sqlalchemy.orm import Session, sessionmaker
from telegram import Update

import agent
import api
import bot
import db as storage
import scheduler

log = logging.getLogger("gym_server")


REQUIRED = ["GROQ_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "DATABASE_URL",
            "TELEGRAM_WEBHOOK_SECRET", "CRON_SECRET", "WEB_PASSWORD"]


def check_environment(full: bool = True) -> None:
    """Fail at startup with ONE clear line naming every missing/invalid setting (names only, never values)."""
    names = REQUIRED if full else ["TELEGRAM_CHAT_ID", "TELEGRAM_WEBHOOK_SECRET", "CRON_SECRET"]
    problems = [f"{n} is missing" for n in names if not os.getenv(n, "").strip()]
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if chat_id and not chat_id.lstrip("-").isdigit():
        problems.append("TELEGRAM_CHAT_ID must be a number")
    secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
    if secret and not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", secret):
        problems.append("TELEGRAM_WEBHOOK_SECRET may only contain letters, digits, _ and -")
    if problems:
        raise RuntimeError("Fix these environment variables (Render -> Environment): " + "; ".join(problems))


def _same(given: Optional[str], expected: str) -> bool:
    return bool(expected) and hmac.compare_digest((given or "").encode(), expected.encode())


def create_server(
    SessionLocal: Optional[sessionmaker[Session]] = None,
    application: Any = None,
    settings: Optional[scheduler.ReminderSettings] = None,
    summarize: Optional[Callable[[str], str]] = None,
    now: Optional[Callable[[], dt.datetime]] = None,
) -> FastAPI:
    if not logging.getLogger().handlers:
        logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)      # Telegram URLs contain the bot token
    storage.database_url()                                    # loads .env when running locally
    check_environment(full=application is None)
    chat_id = int(os.environ["TELEGRAM_CHAT_ID"])
    webhook_secret = os.environ["TELEGRAM_WEBHOOK_SECRET"]
    cron_secret = os.environ["CRON_SECRET"]
    public_url = (os.getenv("PUBLIC_URL") or os.getenv("RENDER_EXTERNAL_URL") or "").rstrip("/")
    settings = settings or scheduler.ReminderSettings.from_env()
    now = now or (lambda: dt.datetime.now(ZoneInfo(settings.timezone)))

    if SessionLocal is None:
        engine = storage.get_engine()
        log.info("Database: %s", storage.describe_engine(engine))
        SessionLocal = storage.make_session_factory(engine)

    coach: Optional[agent.Coach] = None
    if application is None:
        llm = agent.build_llm()
        coach = agent.Coach(llm, SessionLocal)
        summarize = summarize or (lambda prompt: str(llm.invoke(prompt).content))
        application = bot.build_application(os.environ["TELEGRAM_BOT_TOKEN"], chat_id, SessionLocal,
                                            coach, settings, summarize, webhook=True)

    # The website API, unchanged; the web chat shares the coach (separate conversations).
    app = api.create_app(SessionLocal, (lambda: coach) if coach else None)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await application.initialize()
        await application.start()                             # processes the update queue (no polling)
        if public_url:
            await application.bot.set_webhook(f"{public_url}/telegram/webhook", secret_token=webhook_secret,
                                              allowed_updates=Update.ALL_TYPES)
            await application.bot.set_my_commands(bot.COMMANDS)
            log.info("Webhook set. %s", scheduler.describe(settings).replace("\n", " "))
        else:
            log.warning("No PUBLIC_URL/RENDER_EXTERNAL_URL - Telegram webhook not registered")
        yield
        await application.stop()
        await application.shutdown()

    app.router.lifespan_context = lifespan

    @app.post("/telegram/webhook", include_in_schema=False)
    async def telegram_webhook(request: Request,
                               x_telegram_bot_api_secret_token: Optional[str] = Header(default=None)) -> dict:
        if not _same(x_telegram_bot_api_secret_token, webhook_secret):
            raise HTTPException(status_code=403, detail="Forbidden")
        update = Update.de_json(await request.json(), application.bot)
        await application.update_queue.put(update)            # answered in the background - reply fast
        return {"ok": True}

    @app.get("/cron/tick", include_in_schema=False)
    async def cron_tick(x_cron_key: Optional[str] = Header(default=None)) -> dict:
        if not _same(x_cron_key, cron_secret):
            raise HTTPException(status_code=403, detail="Forbidden")
        texts = await asyncio.to_thread(scheduler.tick, SessionLocal, settings, now(), summarize)
        for text in texts:
            for part in bot.split_message(text):
                await application.bot.send_message(chat_id=chat_id, text=part)
        return {"status": "ok", "sent": len(texts)}

    return app


if __name__ == "__main__":                                    # pragma: no cover
    import uvicorn

    uvicorn.run(create_server(), host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
