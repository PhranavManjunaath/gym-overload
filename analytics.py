"""
Analytics - streaks, consistency, milestones and progress summaries.

Plain Python on top of progression_engine.py (whose formulas are unchanged).
Every function takes the dates it needs as arguments, so tests can use fake dates.
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

import progression_engine as pe

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def parse_days(text: str) -> List[str]:
    """'Mon, wednesday,FRI' -> ['mon', 'wed', 'fri'] (week order, no duplicates)."""
    days = [d.strip().lower()[:3] for d in text.split(",") if d.strip()]
    bad = [d for d in days if d not in WEEKDAYS]
    if bad or not days:
        raise ValueError(f"Bad training days '{text}' - use e.g. mon,wed,fri.")
    return sorted(set(days), key=WEEKDAYS.index)


def parse_time(text: str) -> dt.time:
    try:
        return dt.datetime.strptime(text.strip(), "%H:%M").time()
    except ValueError:
        raise ValueError(f"Bad time '{text}' - use 24h HH:MM, e.g. 07:30.") from None


def weekday(d: dt.date) -> str:
    return WEEKDAYS[d.weekday()]


def is_training_day(d: dt.date, training_days: Sequence[str]) -> bool:
    return weekday(d) in training_days


def scheduled_days(training_days: Sequence[str], start: dt.date, end: dt.date) -> List[dt.date]:
    """All training days from start to end (both included)."""
    out, d = [], start
    while d <= end:
        if is_training_day(d, training_days):
            out.append(d)
        d += dt.timedelta(days=1)
    return out


# ---------- consistency ----------

def missed_workout(training_days: Sequence[str], logged: Set[dt.date], today: dt.date) -> bool:
    """Today is a training day and nothing has been logged yet."""
    return is_training_day(today, training_days) and today not in logged


def current_streak(training_days: Sequence[str], logged: Set[dt.date], today: dt.date) -> int:
    """
    Consecutive scheduled training days completed, counting back from the latest one.
    Today only counts once it's logged - an unlogged today doesn't break the streak
    (the day isn't over). Logging on a rest day doesn't count or break anything.
    """
    if not training_days or not logged:
        return 0
    first = min(logged)
    streak, d = 0, today
    if is_training_day(today, training_days) and today not in logged:
        d -= dt.timedelta(days=1)
    while d >= first:
        if is_training_day(d, training_days):
            if d not in logged:
                break
            streak += 1
        d -= dt.timedelta(days=1)
    return streak


def best_streak(training_days: Sequence[str], logged: Set[dt.date], today: dt.date) -> int:
    """Longest run of completed training days since the first log."""
    if not training_days or not logged:
        return 0
    best = run = 0
    for d in scheduled_days(training_days, min(logged), today):
        if d in logged:
            run += 1
            best = max(best, run)
        elif d != today:                       # an unlogged today isn't a miss yet
            run = 0
    return best


def consistency(training_days: Sequence[str], logged: Set[dt.date], today: dt.date, weeks: int = 4) -> Dict[str, Any]:
    """Completed vs planned training days over the last `weeks` weeks (not before the first log)."""
    if not training_days or not logged:
        return {"done": 0, "planned": 0, "percent": None, "weeks": weeks}
    start = max(min(logged), today - dt.timedelta(days=7 * weeks - 1))
    days = [d for d in scheduled_days(training_days, start, today) if not (d == today and d not in logged)]
    done = sum(1 for d in days if d in logged)
    return {"done": done, "planned": len(days), "percent": round(100 * done / len(days)) if days else None,
            "weeks": weeks}


# ---------- milestones ----------

def e1rm_milestone(history: List[pe.Session], new: pe.Session) -> Optional[Dict[str, Any]]:
    """If `new` beats every other session's best e1RM, return the numbers; else None."""
    others = [s for s in history if s is not new]
    if not others:
        return None                                # first session - nothing to beat
    previous = max(pe.best_e1rm(s) for s in others)
    current = pe.best_e1rm(new)
    if current <= previous:
        return None
    return {"e1rm_kg": current, "previous_best_kg": previous, "gain_kg": round(current - previous, 2)}


# ---------- summaries ----------

def best_set(sessions: Iterable[pe.Session]) -> Optional[Dict[str, Any]]:
    """The single set with the highest e1RM (sets over 12 reps ignored, like the engine)."""
    best = None
    for s in sessions:
        for st in s.sets:
            if st.reps > 12:
                continue
            e = round(pe.e1rm_epley(st.weight, st.reps), 2)
            if best is None or e > best["e1rm_kg"]:
                best = {"date": s.date, "weight_kg": st.weight, "reps": st.reps, "e1rm_kg": e}
    return best


def progress_summary(history: List[pe.Session], today: dt.date, weeks: int) -> Dict[str, Any]:
    """e1RM trend, volume trend and best set over the last `weeks` weeks."""
    start = today - dt.timedelta(days=7 * weeks)
    window = [s for s in history if start <= dt.date.fromisoformat(s.date) <= today]
    out: Dict[str, Any] = {"weeks": weeks, "from": start.isoformat(), "to": today.isoformat(),
                           "sessions": len(window)}
    if not window:
        return out
    first, last = window[0], window[-1]
    e_first, e_last = pe.best_e1rm(first), pe.best_e1rm(last)
    v_first, v_last = pe.volume_load(first), pe.volume_load(last)
    out.update({
        "e1rm_first_kg": e_first, "e1rm_last_kg": e_last, "e1rm_change_kg": round(e_last - e_first, 2),
        "volume_first_kg": v_first, "volume_last_kg": v_last, "volume_change_kg": round(v_last - v_first, 2),
        "total_volume_kg": round(sum(pe.volume_load(s) for s in window), 2),
        "best_set": best_set(window),
        "first_date": first.date, "last_date": last.date,
    })
    return out


def week_bounds(d: dt.date) -> tuple[dt.date, dt.date]:
    """Monday and Sunday of the week containing d."""
    monday = d - dt.timedelta(days=d.weekday())
    return monday, monday + dt.timedelta(days=6)
