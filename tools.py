"""
Agent tools - the only way the LLM touches data or numbers.

Each tool is a plain Python function that takes a DB session and returns a
JSON-friendly dict. Every number in a result comes from progression_engine.py
or straight from the database; the LLM only puts the result into words.

Results always have a "status":
    ok                    - worked; see the other fields
    parse_error           - couldn't read the workout text; "message" says why
    unknown_exercise      - exercise not set up yet; ask the user to add it
    need_starting_weight  - no history; ask the user for a starting weight (never guess)
    error                 - invalid input; "message" says why

Each call is one transaction: on failure nothing is saved. The caller commits on success.
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

import db as storage
import parser as workout_parser
import progression_engine as pe

Result = Dict[str, Any]


# ---------- helpers ----------

def _sets(sets: List[pe.SetLog]) -> List[Dict[str, Any]]:
    return [{"weight_kg": s.weight, "reps": s.reps, "rpe": s.rpe} for s in sets]


def _session(s: pe.Session) -> Dict[str, Any]:
    return {
        "date": s.date,
        "deload": s.is_deload,
        "sets": _sets(s.sets),
        "working_weight_kg": pe.working_weight(s),
        "total_reps": pe.total_reps(s),
    }


def _settings(cfg: pe.ExerciseConfig) -> Dict[str, Any]:
    return {"rep_min": cfg.rep_min, "rep_max": cfg.rep_max,
            "increment_kg": cfg.increment, "target_sets": cfg.target_sets}


def _unknown(name: str) -> Result:
    return {"status": "unknown_exercise", "exercises": [storage.normalize_name(name)],
            "message": "This exercise isn't set up yet. Ask the user for its equipment "
                       "(and rep range / increment if not default), then call add_exercise."}


def _pct(x: float) -> str:
    return f"{x * 100:g}%"


def rule_explained(action: str, cfg: pe.ExerciseConfig) -> str:
    """The progression rule behind an action, filled in with this exercise's settings."""
    return {
        "increase_weight": f"All working sets reached {cfg.rep_max} reps (RPE <= {cfg.max_rpe_for_increase:g} "
                           f"where logged) -> add {cfg.increment:g} kg and restart at {cfg.rep_min} reps.",
        "add_reps": f"Every set was at least {cfg.rep_min} reps -> same weight, +1 rep on each set "
                    f"below {cfg.rep_max}.",
        "repeat": f"At least one set was under {cfg.rep_min} reps -> repeat the same weight.",
        "reduce_weight": f"Two sessions in a row under {cfg.rep_min} reps at the same weight -> "
                         f"{_pct(cfg.failure_drop_pct)} of that weight, rounded down to a multiple of "
                         f"{cfg.increment:g} kg.",
        "deload": f"{cfg.plateau_window} sessions in a row at the same weight with no gain in total reps "
                  f"(plateau) -> one deload session at {_pct(cfg.deload_pct)}, rounded down to a multiple "
                  f"of {cfg.increment:g} kg.",
        "resume": "Last session was a deload -> go back to the weight used before it.",
    }[action]


# ---------- tools ----------

def add_exercise(
    session: Session,
    name: str,
    equipment: str = "barbell",
    rep_min: Optional[int] = None,
    rep_max: Optional[int] = None,
    increment_kg: Optional[float] = None,
    target_sets: Optional[int] = None,
) -> Result:
    """Set up a new exercise. Defaults: 6-10 reps, 3 sets, +2.5 kg barbell / +2 kg dumbbell."""
    try:
        ex = storage.add_exercise(session, name, equipment, rep_min, rep_max, increment_kg, target_sets)
    except ValueError as e:
        session.rollback()
        return {"status": "error", "message": str(e)}
    return {"status": "ok", "exercise": ex.name, "equipment": ex.equipment,
            "settings": _settings(storage.get_config(session, ex.name))}


def list_exercises(session: Session) -> Result:
    """All set-up exercises with their settings."""
    return {"status": "ok", "exercises": [
        {"exercise": ex.name, "equipment": ex.equipment, "settings": _settings(storage.get_config(session, ex.name))}
        for ex in storage.list_exercises(session)
    ]}


def log_workout(session: Session, text: str, today: Optional[dt.date] = None) -> Result:
    """Parse a workout message (e.g. 'bench 60x10,10,9 @8') and save it. All lines or nothing."""
    try:
        entries = workout_parser.parse_message(text, today)
    except workout_parser.ParseError as e:
        return {"status": "parse_error", "message": str(e)}

    missing = sorted({e.exercise for e in entries if storage.get_exercise(session, e.exercise) is None})
    if missing:
        return {"status": "unknown_exercise", "exercises": missing,
                "message": "Nothing saved. Set these exercises up first (add_exercise), then log again."}

    try:
        for e in entries:
            storage.log_session(session, e.exercise, e.date, e.sets, e.is_deload)
    except ValueError as err:
        session.rollback()
        return {"status": "error", "message": f"Nothing saved: {err}"}

    logged = []
    for e in entries:
        s = pe.Session(e.date.isoformat(), e.sets, e.is_deload)
        logged.append({"exercise": e.exercise, **_session(s), "volume_kg": pe.volume_load(s)})
    return {"status": "ok", "logged": logged}


def recommend_next(session: Session, exercise: str) -> Result:
    """Next session's weight and reps, with the rule that fired and the sessions it was based on."""
    try:
        cfg = storage.get_config(session, exercise)
    except storage.ExerciseNotFound:
        return _unknown(exercise)

    history = storage.get_history(session, cfg.name)
    if not history:
        return {"status": "need_starting_weight", "exercise": cfg.name, "settings": _settings(cfg),
                "message": "No history for this exercise. Ask the user for a starting weight - never guess."}

    rec = pe.next_target(cfg, history)
    return {
        "status": "ok",
        "exercise": cfg.name,
        "next": {"weight_kg": rec.weight, "target_reps": rec.target_reps},
        "rule": rec.action,
        "rule_explained": rule_explained(rec.action, cfg),
        "reason": rec.reason,
        "based_on": {
            "last_session": _session(history[-1]),
            "recent_sessions": [_session(s) for s in history[-cfg.plateau_window:]],
            "settings": _settings(cfg),
        },
        "e1rm_last_kg": rec.e1rm_last,   # progress tracking only - not used to pick the weight
    }


def plan_first_session(session: Session, exercise: str, starting_weight_kg: float) -> Result:
    """First session for an exercise with no history, at the weight the USER chose."""
    try:
        cfg = storage.get_config(session, exercise)
    except storage.ExerciseNotFound:
        return _unknown(exercise)
    if storage.get_history(session, cfg.name):
        return {"status": "error", "message": "This exercise already has history - use recommend_next."}
    if starting_weight_kg <= 0:
        return {"status": "error", "message": "Starting weight must be more than 0 kg."}
    return {
        "status": "ok",
        "exercise": cfg.name,
        "next": {"weight_kg": float(starting_weight_kg), "target_reps": [cfg.rep_min] * cfg.target_sets},
        "rule": "starting_weight",
        "rule_explained": f"No history yet: start at the weight you chose, aiming for {cfg.rep_min} reps "
                          f"on each of {cfg.target_sets} sets. Progression starts after this session.",
        "based_on": {"starting_weight_from": "user", "settings": _settings(cfg)},
    }


def get_progress(session: Session, exercise: str, last_n: Optional[int] = None) -> Result:
    """Per-session stats for charts: working weight, total reps, volume, best e1RM (Epley)."""
    try:
        cfg = storage.get_config(session, exercise)
    except storage.ExerciseNotFound:
        return _unknown(exercise)
    history = storage.get_history(session, cfg.name)
    if last_n is not None:
        if last_n < 1:
            return {"status": "error", "message": "last_n must be at least 1."}
        history = history[-last_n:]
    return {"status": "ok", "exercise": cfg.name, "sessions": [
        {"date": s.date, "deload": s.is_deload, "working_weight_kg": pe.working_weight(s),
         "total_reps": pe.total_reps(s), "volume_kg": pe.volume_load(s), "best_e1rm_kg": pe.best_e1rm(s)}
        for s in history
    ]}
