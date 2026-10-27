"""
API - a thin HTTP layer over tools.py for the website (frontend/).

No business logic here: every number comes from tools.py / progression_engine.py,
and every result keeps the tools' {"status": ...} shape. Separate from the
Telegram bot (never imports bot.py).

Run: uvicorn api:create_app --factory --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

import datetime as dt
import hmac
import os
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, sessionmaker

import agent
import db as storage
import parser as workout_parser
import progression_engine as pe
import scheduler
import tools

Result = Dict[str, Any]
EVIDENCE_MARKER = "\n\n📊 Numbers used\n"       # added by agent.Coach.chat
RECENT_LIMIT = 8
DEFAULT_ORIGINS = "http://localhost:3000,http://127.0.0.1:3000"


class WorkoutIn(BaseModel):
    text: str = Field(max_length=5000)
    date: Optional[dt.date] = None                  # default: today


class ExerciseIn(BaseModel):
    name: str = Field(max_length=100)
    equipment: str = "barbell"
    rep_min: Optional[int] = None
    rep_max: Optional[int] = None
    increment_kg: Optional[float] = None
    target_sets: Optional[int] = None


class StartIn(BaseModel):
    starting_weight_kg: float


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    conversation_id: str = Field(pattern=r"^[A-Za-z0-9-]{8,64}$")


def _sets(sets: List[pe.SetLog]) -> List[Dict[str, Any]]:
    return [{"weight_kg": s.weight, "reps": s.reps, "rpe": s.rpe} for s in sets]


def create_app(
    SessionLocal: Optional[sessionmaker[Session]] = None,
    coach_factory: Optional[Callable[[], agent.Coach]] = None,
    password: Optional[str] = None,
    today: Callable[[], dt.date] = dt.date.today,
) -> FastAPI:
    """Build the app. Defaults: DATABASE_URL, the Groq coach and WEB_PASSWORD from .env."""
    if SessionLocal is None:
        SessionLocal = storage.make_session_factory(storage.get_engine())
    if password is None:
        storage.database_url()                       # loads .env
        password = os.getenv("WEB_PASSWORD", "")
    coach_factory = coach_factory or (lambda: agent.create_coach(SessionLocal))
    coach_cache: Dict[str, agent.Coach] = {}

    def run(fn: Callable[..., Result], **kwargs: Any) -> Result:
        with SessionLocal() as s:
            result = fn(s, **kwargs)
            if result.get("status") == "ok":
                s.commit()
            else:
                s.rollback()
            return result

    def check_password(x_app_password: Optional[str] = Header(default=None)) -> None:
        if password and not hmac.compare_digest((x_app_password or "").encode(), password.encode()):
            raise HTTPException(status_code=401, detail="Password required")

    def workout_day(d: Optional[dt.date]) -> dt.date:
        day = d or today()
        if day > today():
            raise HTTPException(status_code=422, detail="Date can't be in the future.")
        return day

    app = FastAPI(title="Gym Overload API", docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in os.getenv("WEB_ORIGINS", DEFAULT_ORIGINS).split(",") if o.strip()],
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-App-Password"],
    )

    @app.get("/api/health")
    def health() -> Result:
        return {"status": "ok"}

    @app.get("/api/auth")
    def auth_info() -> Result:
        return {"status": "ok", "password_required": bool(password)}

    r = APIRouter(prefix="/api", dependencies=[Depends(check_password)])

    @r.get("/meta")
    def meta() -> Result:
        d = pe.ExerciseConfig("_")
        return {"status": "ok", "log_help": workout_parser.HELP,
                "defaults": {"rep_min": d.rep_min, "rep_max": d.rep_max, "target_sets": d.target_sets},
                "default_increments_kg": storage.DEFAULT_INCREMENTS}

    @r.get("/dashboard")
    def dashboard() -> Result:
        with SessionLocal() as s:
            exercises = tools.list_exercises(s)["exercises"]
            nxt = [tools.recommend_next(s, e["exercise"]) for e in exercises]
            recent = [
                {"exercise": e["exercise"], **sess}
                for e in exercises
                for sess in tools.get_progress(s, e["exercise"], last_n=RECENT_LIMIT)["sessions"]
            ]
        recent.sort(key=lambda x: (x["date"], x["exercise"]), reverse=True)
        return {"status": "ok", "exercises": exercises, "next": nxt, "recent": recent[:RECENT_LIMIT]}

    @r.get("/exercises")
    def list_exercises() -> Result:
        return run(tools.list_exercises)

    @r.post("/exercises")
    def add_exercise(body: ExerciseIn) -> Result:
        return run(tools.add_exercise, name=body.name, equipment=body.equipment, rep_min=body.rep_min,
                   rep_max=body.rep_max, increment_kg=body.increment_kg, target_sets=body.target_sets)

    @r.get("/next")
    def next_all() -> Result:
        with SessionLocal() as s:
            exercises = tools.list_exercises(s)["exercises"]
            return {"status": "ok", "recommendations": [tools.recommend_next(s, e["exercise"]) for e in exercises]}

    @r.get("/exercises/{name}/next")
    def next_one(name: str) -> Result:
        return run(tools.recommend_next, exercise=name)

    @r.post("/exercises/{name}/first-session")
    def first_session(name: str, body: StartIn) -> Result:
        return run(tools.plan_first_session, exercise=name, starting_weight_kg=body.starting_weight_kg)

    @r.get("/exercises/{name}/progress")
    def progress(name: str, last_n: Optional[int] = None) -> Result:
        return run(tools.get_progress, exercise=name, last_n=last_n)

    @r.post("/workouts/preview")
    def preview(body: WorkoutIn) -> Result:
        """Parse only - nothing is saved. The parser is the authority."""
        day = workout_day(body.date)
        try:
            entries = workout_parser.parse_message(body.text, today=day)
        except workout_parser.ParseError as e:
            return {"status": "parse_error", "message": str(e)}
        with SessionLocal() as s:
            known = {e["exercise"] for e in tools.list_exercises(s)["exercises"]}
        return {"status": "ok",
                "entries": [{"exercise": e.exercise, "date": e.date.isoformat(), "deload": e.is_deload,
                             "sets": _sets(e.sets)} for e in entries],
                "unknown_exercises": sorted({e.exercise for e in entries} - known)}

    @r.post("/workouts")
    def save(body: WorkoutIn) -> Result:
        day = workout_day(body.date)
        with SessionLocal() as s:
            result = tools.log_workout(s, body.text, today=day)
            if result["status"] != "ok":
                s.rollback()
                return result
            s.commit()
            names = list(dict.fromkeys(e["exercise"] for e in result["logged"]))
            return {**result, "recommendations": [tools.recommend_next(s, n) for n in names]}

    @r.post("/coach")
    def coach(body: ChatIn) -> Result:
        try:
            if "coach" not in coach_cache:
                coach_cache["coach"] = coach_factory()
            reply = coach_cache["coach"].chat(f"web-{body.conversation_id}", body.message)
        except RuntimeError as e:                    # e.g. GROQ_API_KEY missing
            return {"status": "error", "message": f"The AI coach isn't set up: {e}."}
        except Exception:
            return {"status": "error",
                    "message": "The AI coach is unavailable right now. Nothing was lost - the other pages still work."}
        text, _, evidence = reply.partition(EVIDENCE_MARKER)
        return {"status": "ok", "reply": text, "evidence": evidence or None}

    @r.get("/reminders")
    def reminders() -> Result:
        try:
            st = scheduler.ReminderSettings.from_env()
        except ValueError as e:
            return {"status": "error", "message": str(e)}
        hm = lambda t: t.strftime("%H:%M")
        return {"status": "ok", "timezone": st.timezone, "workout_days": st.workout_days,
                "workout_time": hm(st.workout_time), "missed_check_time": hm(st.missed_check_time),
                "meal_times": [hm(t) for t in st.meal_times],
                "note": "Change them in .env and restart the bot."}

    app.include_router(r)
    return app
