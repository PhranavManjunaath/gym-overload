"""
Reports - the weekly report and CSV export.

All numbers are computed here in plain Python (via progression_engine / analytics).
The LLM may only add a 3-4 line summary written FROM those numbers, and the summary
is dropped if it contains any number that isn't in the stats.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
from typing import Any, Callable, Dict, Optional

from sqlalchemy.orm import Session

import analytics
import db as storage
import progression_engine as pe
import tools
from agent import ungrounded_numbers

Summarize = Callable[[str], str]

SUMMARY_PROMPT = """Write a 3-4 line, short and motivating summary of this training week for the lifter.
Use ONLY numbers that appear in the stats below - copy them exactly, never calculate new ones.
Plain text, no markdown, no diet or calorie advice.

{stats}"""


def weekly_stats(session: Session, today: dt.date) -> Dict[str, Any]:
    """Numbers for the week (Mon-Sun) containing `today`, compared with the week before."""
    mon, sun = analytics.week_bounds(today)
    prev_mon, prev_sun = mon - dt.timedelta(days=7), sun - dt.timedelta(days=7)
    in_week = lambda s, a, b: a <= dt.date.fromisoformat(s.date) <= b
    days = tools.get_schedule(session)["training_days"]
    logged = storage.session_dates(session)

    planned = analytics.scheduled_days(days, mon, sun)
    lifts, total_volume, sessions = [], 0.0, 0
    for ex in storage.list_exercises(session):
        history = storage.get_history(session, ex.name)
        week = [s for s in history if in_week(s, mon, sun)]
        if not week:
            continue
        prev = [s for s in history if in_week(s, prev_mon, prev_sun)]
        best = max(pe.best_e1rm(s) for s in week)
        prev_best = max(pe.best_e1rm(s) for s in prev) if prev else None
        cfg = storage.get_config(session, ex.name)
        sessions += len(week)
        total_volume += sum(pe.volume_load(s) for s in week)
        lifts.append({
            "exercise": ex.name, "sessions": len(week), "best_e1rm_kg": best,
            "previous_week_best_e1rm_kg": prev_best,
            "change_kg": round(best - prev_best, 2) if prev_best is not None else None,
            "plateau": pe.detect_plateau(cfg, history),
            "deload": any(s.is_deload for s in week),
        })

    target = storage.get_setting(session, "protein_target_g")
    protein_days = None
    if target:
        meals = storage.meals_between(session, mon, min(sun, today))
        totals: Dict[dt.date, float] = {}
        for m in meals:
            if m.protein_g is not None:
                totals[m.date] = totals.get(m.date, 0) + m.protein_g
        tracked = (min(sun, today) - mon).days + 1
        protein_days = {"on_target": sum(1 for v in totals.values() if v >= float(target)),
                        "days": tracked, "target_g": float(target)}

    return {
        "week": f"{mon.isoformat()} to {sun.isoformat()}",
        "training_days_planned": len(planned),
        "training_days_done": sum(1 for d in planned if d in logged),
        "sessions_logged": sessions,
        "total_volume_kg": round(total_volume, 2),
        "lifts": lifts,
        "protein": protein_days,
        "streak": analytics.current_streak(days, logged, today),
    }


def stats_text(st: Dict[str, Any]) -> str:
    """The report body - plain Python formatting of weekly_stats."""
    f = lambda x: f"{x:g}"
    lines = [f"📅 Week {st['week']}",
             f"Training days: {st['training_days_done']}/{st['training_days_planned']} planned · "
             f"{st['sessions_logged']} exercise sessions · streak {st['streak']}",
             f"Total volume: {f(st['total_volume_kg'])} kg"]
    for l in st["lifts"]:
        line = f"• {l['exercise']}: best e1RM {f(l['best_e1rm_kg'])} kg"
        if l["change_kg"] is not None:
            sign = "+" if l["change_kg"] >= 0 else ""
            line += f" ({sign}{f(l['change_kg'])} kg vs last week)"
        else:
            line += " (no sessions last week)"
        if l["plateau"]:
            line += " · plateau"
        if l["deload"]:
            line += " · deload week"
        lines.append(line)
    if not st["lifts"]:
        lines.append("• No sessions logged this week.")
    p = st["protein"]
    if p:
        lines.append(f"Protein: {p['on_target']}/{p['days']} days at or above your {f(p['target_g'])} g target")
    return "\n".join(lines)


def summarize_checked(summarize: Optional[Summarize], body: str) -> Optional[str]:
    """LLM summary of the stats, or None if there's no LLM, it fails, or it invents a number."""
    if summarize is None:
        return None
    try:
        text = summarize(SUMMARY_PROMPT.format(stats=body)).strip()
    except Exception:
        return None
    if not text or ungrounded_numbers(text, [body]):
        return None
    return "\n".join(text.splitlines()[:4])


def weekly_report(session: Session, today: dt.date, summarize: Optional[Summarize] = None) -> str:
    body = stats_text(weekly_stats(session, today))
    summary = summarize_checked(summarize, body)
    return f"{summary}\n\n{body}" if summary else body


# ---------- CSV export ----------

def _csv(rows: list, fields: list) -> str:
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=fields, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return out.getvalue()


def export_workouts_csv(session: Session) -> str:
    return _csv(storage.all_sets(session), ["date", "exercise", "set", "weight_kg", "reps", "rpe", "deload"])


def export_meals_csv(session: Session) -> str:
    rows = [{"date": m.date.isoformat(), "meal_id": m.id, "text": m.text, "protein_g": m.protein_g,
             "protein_estimated": m.protein_estimated} for m in storage.all_meals(session)]
    return _csv(rows, ["date", "meal_id", "text", "protein_g", "protein_estimated"])
