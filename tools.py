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
import os
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

import analytics
import db as storage
import nutrition
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

    logged, milestones = [], []
    for e in entries:
        s = pe.Session(e.date.isoformat(), e.sets, e.is_deload)
        logged.append({"exercise": e.exercise, **_session(s), "volume_kg": pe.volume_load(s)})
        history = storage.get_history(session, e.exercise)
        others = list(history)
        others.remove(s)                       # the session just saved (dataclasses compare by value)
        if m := analytics.e1rm_milestone(others + [s], s):
            milestones.append({"exercise": e.exercise, "date": s.date, **m})
    return {"status": "ok", "logged": logged, "milestones": milestones}


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


# ---------- history & analysis ----------

def get_history(session: Session, exercise: str, n: int = 5) -> Result:
    """The last `n` sessions of an exercise with every set, newest last."""
    try:
        cfg = storage.get_config(session, exercise)
    except storage.ExerciseNotFound:
        return _unknown(exercise)
    if n < 1:
        return {"status": "error", "message": "n must be at least 1."}
    history = storage.get_history(session, cfg.name)[-n:]
    return {"status": "ok", "exercise": cfg.name, "sessions": [_session(s) for s in history]}


def check_plateau(session: Session, exercise: str) -> Result:
    """Plateau check from the engine: same weight with no gain in total reps over the window."""
    try:
        cfg = storage.get_config(session, exercise)
    except storage.ExerciseNotFound:
        return _unknown(exercise)
    history = storage.get_history(session, cfg.name)
    if not history:
        return {"status": "error", "message": f"No sessions logged for {cfg.name} yet."}
    window = [s for s in history if not s.is_deload][-cfg.plateau_window:]
    return {"status": "ok", "exercise": cfg.name, "plateau": pe.detect_plateau(cfg, history),
            "rule": f"Plateau = {cfg.plateau_window} sessions in a row at the same weight with no gain "
                    f"in total reps (counted since the last deload).",
            "sessions_checked": [_session(s) for s in window]}


def progress_summary(session: Session, exercise: str, weeks: int = 4,
                     today: Optional[dt.date] = None) -> Result:
    """e1RM trend, volume trend and best set over the last `weeks` weeks (computed in Python)."""
    try:
        cfg = storage.get_config(session, exercise)
    except storage.ExerciseNotFound:
        return _unknown(exercise)
    if not 1 <= weeks <= 104:
        return {"status": "error", "message": "weeks must be between 1 and 104."}
    summary = analytics.progress_summary(storage.get_history(session, cfg.name), today or dt.date.today(), weeks)
    return {"status": "ok", "exercise": cfg.name, **summary}


def update_exercise_settings(session: Session, exercise: str, rep_min: Optional[int] = None,
                             rep_max: Optional[int] = None, increment_kg: Optional[float] = None,
                             target_sets: Optional[int] = None) -> Result:
    """Change rep range / weight jump / sets. Settings left empty stay the same."""
    try:
        ex = storage.update_exercise_settings(session, exercise, rep_min, rep_max, increment_kg, target_sets)
    except storage.ExerciseNotFound:
        return _unknown(exercise)
    except ValueError as e:
        session.rollback()
        return {"status": "error", "message": str(e)}
    return {"status": "ok", "exercise": ex.name, "settings": _settings(storage.get_config(session, ex.name))}


# ---------- long-term memory ----------

def save_preference(session: Session, key: str, value: str) -> Result:
    """Remember something about the user, e.g. key='dislikes', value='lunges'."""
    try:
        p = storage.save_preference(session, key, value)
    except ValueError as e:
        return {"status": "error", "message": str(e)}
    return {"status": "ok", "key": p.key, "value": p.value}


def set_goal(session: Session, goal: str) -> Result:
    goal = goal.strip()
    if not goal:
        return {"status": "error", "message": "Goal can't be empty."}
    storage.set_setting(session, "goal", goal[:300])
    return {"status": "ok", "goal": goal[:300]}


def _default_days() -> List[str]:
    try:
        return analytics.parse_days(os.environ.get("WORKOUT_DAYS", "mon,wed,fri"))
    except ValueError:
        return ["mon", "wed", "fri"]


def _default_time() -> str:
    try:
        return analytics.parse_time(os.environ.get("WORKOUT_REMINDER_TIME", "07:00")).strftime("%H:%M")
    except ValueError:
        return "07:00"


def get_schedule(session: Session) -> Result:
    """Training days, reminder time and per-day exercise plan (app settings, else .env defaults)."""
    days = storage.get_setting(session, "training_days")
    time = storage.get_setting(session, "workout_time")
    return {"status": "ok",
            "training_days": analytics.parse_days(days) if days else _default_days(),
            "workout_time": time or _default_time(),
            "day_plan": storage.get_day_plan(session),
            "source": "app" if days or time else "defaults"}


def set_schedule(session: Session, training_days: Optional[str] = None, workout_time: Optional[str] = None) -> Result:
    """Set training days ('mon,wed,fri') and/or the reminder time ('07:30')."""
    try:
        if training_days is not None:
            storage.set_setting(session, "training_days", ",".join(analytics.parse_days(training_days)))
        if workout_time is not None:
            storage.set_setting(session, "workout_time", analytics.parse_time(workout_time).strftime("%H:%M"))
    except ValueError as e:
        session.rollback()
        return {"status": "error", "message": str(e)}
    return get_schedule(session)


def set_day_plan(session: Session, day: str, exercises: List[str]) -> Result:
    """Which exercises are trained on a weekday - used for that day's reminder."""
    try:
        names = storage.set_day_plan(session, day, exercises)
    except storage.ExerciseNotFound as e:
        session.rollback()
        return {"status": "unknown_exercise", "message": str(e)}
    except ValueError as e:
        session.rollback()
        return {"status": "error", "message": str(e)}
    return {"status": "ok", "day": day.strip().lower()[:3], "exercises": names}


def streak(session: Session, today: Optional[dt.date] = None) -> Result:
    """Current/best streak of completed training days and consistency over the last 4 weeks."""
    today = today or dt.date.today()
    days = get_schedule(session)["training_days"]
    logged = storage.session_dates(session)
    return {"status": "ok", "training_days": days,
            "current_streak": analytics.current_streak(days, logged, today),
            "best_streak": analytics.best_streak(days, logged, today),
            "consistency": analytics.consistency(days, logged, today),
            "logged_today": today in logged}


def memory_context(session: Session) -> str:
    """Goal, schedule, protein target and preferences - loaded into the agent's prompt every turn."""
    sched = get_schedule(session)
    names = [e.name for e in storage.list_exercises(session)]
    lines = [f"Goal: {storage.get_setting(session, 'goal') or 'not set'}",
             f"Exercises set up (exact names for tools): {', '.join(names) if names else 'none yet'}",
             f"Training days: {', '.join(sched['training_days'])} (reminder {sched['workout_time']})"]
    for day, names in sched["day_plan"].items():
        lines.append(f"Plan {day}: {', '.join(names)}")
    target = storage.get_setting(session, "protein_target_g")
    lines.append(f"Protein target: {target + ' g/day' if target else 'not set'}")
    prefs = storage.list_preferences(session)
    lines += [f"Preference - {p.key}: {p.value}" for p in prefs] or ["Preferences: none saved"]
    return "\n".join(lines)


# ---------- meals & protein (tracking only - no diet advice) ----------

def _meal(m: storage.Meal) -> Dict[str, Any]:
    return {"id": m.id, "date": m.date.isoformat(), "text": m.text, "protein_g": m.protein_g,
            "protein_estimated": m.protein_estimated}


def protein_day(session: Session, day: Optional[dt.date] = None) -> Result:
    """Meals on a day, total protein so far and the user's own target."""
    day = day or dt.date.today()
    meals = storage.meals_between(session, day, day)
    known = [m.protein_g for m in meals if m.protein_g is not None]
    target = storage.get_setting(session, "protein_target_g")
    return {"status": "ok", "date": day.isoformat(), "meals": [_meal(m) for m in meals],
            "total_protein_g": round(sum(known), 1),
            "meals_missing_protein": sum(1 for m in meals if m.protein_g is None),
            "any_estimated": any(m.protein_estimated and m.protein_g is not None for m in meals),
            "target_g": float(target) if target else None,
            "remaining_g": round(max(float(target) - sum(known), 0), 1) if target else None}


def log_meal(session: Session, text: str, today: Optional[dt.date] = None) -> Result:
    """Store a meal with protein estimated from a fixed food table (or the user's own number)."""
    est = nutrition.estimate_protein(text)
    try:
        meal = storage.add_meal(session, today or dt.date.today(), text, est.protein_g, est.estimated)
    except ValueError as e:
        return {"status": "error", "message": str(e)}
    out: Result = {"status": "ok", "meal": _meal(meal), "breakdown": est.items, "unknown_items": est.unknown}
    if est.protein_g is None:
        out["message"] = (f"Couldn't estimate protein for: {', '.join(est.unknown)}. "
                          f"Tell me the grams and I'll store your number (meal {meal.id}).")
    out["day"] = protein_day(session, meal.date)
    return out


def correct_meal_protein(session: Session, meal_id: int, protein_g: float) -> Result:
    """Replace a meal's protein with the user's own number."""
    try:
        meal = storage.set_meal_protein(session, meal_id, protein_g)
    except ValueError as e:
        return {"status": "error", "message": str(e)}
    return {"status": "ok", "meal": _meal(meal), "day": protein_day(session, meal.date)}


def set_protein_target(session: Session, grams: float) -> Result:
    """The user's own daily protein target (grams)."""
    if not 0 < grams <= 500:
        return {"status": "error", "message": "Protein target must be between 1 and 500 g."}
    storage.set_setting(session, "protein_target_g", f"{grams:g}")
    return {"status": "ok", "target_g": float(grams)}
