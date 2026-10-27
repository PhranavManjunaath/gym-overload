"""
Formatting - turns tool results into short plain text for Telegram.

Deterministic Python, no LLM: the "Numbers used" block under every coach reply
comes from here, so the numbers you see are exactly what the engine returned.
"""
from __future__ import annotations

from typing import Any, Dict, List

Result = Dict[str, Any]


def kg(x: float) -> str:
    """62.5 -> '62.5 kg', 60.0 -> '60 kg'."""
    return f"{x:g} kg"


def format_sets(sets: List[Dict[str, Any]]) -> str:
    """[{weight_kg, reps, rpe}] -> '60 kg × 10, 10, 9 (RPE 8, 8, 9)' or '60×10, 62.5×8'."""
    if not sets:
        return "no sets"
    weights = {s["weight_kg"] for s in sets}
    rpes = [s.get("rpe") for s in sets]
    if len(weights) == 1:
        text = f"{kg(sets[0]['weight_kg'])} × " + ", ".join(str(s["reps"]) for s in sets)
    else:
        text = ", ".join(f"{s['weight_kg']:g}×{s['reps']}" for s in sets)
    if any(r is not None for r in rpes):
        text += " (RPE " + ", ".join("-" if r is None else f"{r:g}" for r in rpes) + ")"
    return text


def format_targets(nxt: Dict[str, Any]) -> str:
    """{'weight_kg': 62.5, 'target_reps': [6, 6, 6]} -> '62.5 kg × 6, 6, 6'."""
    return f"{kg(nxt['weight_kg'])} × " + ", ".join(str(r) for r in nxt["target_reps"])


def format_session(s: Dict[str, Any]) -> str:
    tag = " [deload]" if s.get("deload") else ""
    return f"{s['date']}: {format_sets(s['sets'])}{tag}"


def format_recommendation(r: Result) -> str:
    """recommend_next / plan_first_session result -> evidence block."""
    if r.get("status") != "ok":
        return r.get("message", "No recommendation.")
    lines = [f"Next {r['exercise']}: {format_targets(r['next'])}",
             f"Rule: {r['rule']} - {r['rule_explained']}"]
    based = r.get("based_on", {})
    recent = based.get("recent_sessions") or []
    if len(recent) > 1:
        lines.append("Based on:")
        lines += [f"  • {format_session(s)} (total reps {s['total_reps']})" for s in recent]
    elif "last_session" in based:
        lines.append(f"Based on: {format_session(based['last_session'])}")
    elif based.get("starting_weight_from") == "user":
        lines.append("Based on: the starting weight you gave")
    return "\n".join(lines)


def format_logged(r: Result) -> str:
    """log_workout result -> 'Saved bench 2026-10-27: 60 kg × 10, 10, 9'."""
    if r.get("status") != "ok":
        return r.get("message", "Nothing saved.")
    return "\n".join(f"Saved {e['exercise']} {format_session(e)}" for e in r["logged"])


def format_progress(r: Result) -> str:
    if r.get("status") != "ok":
        return r.get("message", "No data.")
    if not r["sessions"]:
        return f"No sessions logged for {r['exercise']} yet."
    lines = [f"{r['exercise']} - last {len(r['sessions'])} sessions:"]
    for s in r["sessions"]:
        tag = " [deload]" if s["deload"] else ""
        lines.append(f"  • {s['date']}: {kg(s['working_weight_kg'])}, {s['total_reps']} reps, "
                     f"volume {kg(s['volume_kg'])}, e1RM {kg(s['best_e1rm_kg'])}{tag}")
    return "\n".join(lines)


def format_exercises(r: Result) -> str:
    if not r.get("exercises"):
        return "No exercises yet. Tell me one, e.g. 'add bench press, barbell'."
    lines = ["Your exercises:"]
    for e in r["exercises"]:
        st = e["settings"]
        lines.append(f"  • {e['exercise']} ({e['equipment']}): {st['rep_min']}-{st['rep_max']} reps, "
                     f"{st['target_sets']} sets, +{kg(st['increment_kg'])}")
    return "\n".join(lines)


def format_any(tool_name: str, r: Result) -> str:
    """Best plain-text view of any tool result (used as the safe fallback reply)."""
    if r.get("status") not in ("ok", None):
        return r.get("message", f"{tool_name}: {r.get('status')}")
    return {
        "recommend_next": format_recommendation,
        "plan_first_session": format_recommendation,
        "log_workout": format_logged,
        "get_progress": format_progress,
        "list_exercises": format_exercises,
    }.get(tool_name, lambda x: f"Done: {x.get('exercise', tool_name)}")(r)
