"""
Agent evaluation with the REAL LLM (Groq) - run manually:  python -m tests.eval_agent

Not collected by pytest (pytest never calls Groq). Uses a throwaway SQLite database
seeded through tools.py, so your real data is never touched.

Reports (cases that failed on network/API errors after retries are listed separately,
not counted as wrong answers):
  - tool-selection accuracy: the first tool the agent called is one of the expected tools
  - expected tool used at all: it was called at some point in the turn
  - grounded replies: every number in the final reply appears in a tool output,
    the user's message, the saved memory or today's date ("no hallucinated numbers")
  - first-draft grounding: how often the verify step did NOT have to step in
"""
from __future__ import annotations

import datetime as dt
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import List, Tuple

import agent
import db as storage
import tools

TODAY = dt.date.today()
PAUSE_S = 2.0                       # be gentle with Groq rate limits
MAX_ATTEMPTS = 3

# (message, acceptable first tools)
CASES: List[Tuple[str, Tuple[str, ...]]] = [
    ("what should I bench next?", ("recommend_next",)),
    ("bench press 60x10,10,9 @8", ("log_workout",)),
    ("show my last 3 squat sessions", ("get_history",)),
    ("am I stuck on squat?", ("check_plateau",)),
    ("how has my bench press progressed over the last 4 weeks?", ("progress_summary",)),
    ("change squat to 3-5 reps", ("update_exercise_settings",)),
    ("I hate lunges, never suggest them", ("save_preference",)),
    ("my goal is to bench 100 kg by June", ("set_goal",)),
    ("I train tuesday, thursday and saturday now", ("set_schedule",)),
    ("on tuesdays I do bench press and squat", ("set_day_plan",)),
    ("what's my streak?", ("get_streak",)),
    ("lunch: chicken breast 200g, rice 150g", ("log_meal",)),
    ("set my protein target to 150 g", ("set_protein_target",)),
    ("how much protein have I had today?", ("protein_today",)),
    ("add leg press, machine, 5 kg jumps", ("add_exercise",)),
    ("what exercises do I have?", ("list_exercises",)),
    ("what should I deadlift?", ("recommend_next",)),
    ("give me the per-session numbers behind my db curl chart", ("get_progress", "get_history")),
    ("meal 3 actually had 45 g protein", ("correct_meal_protein",)),
    ("start deadlift at 100 kg", ("plan_first_session",)),
]


def seed(SessionLocal: storage.sessionmaker) -> None:
    d = lambda n: (TODAY - dt.timedelta(days=n)).isoformat()
    with SessionLocal.begin() as s:
        tools.add_exercise(s, "bench press")
        tools.add_exercise(s, "squat")
        tools.add_exercise(s, "db curl", equipment="dumbbell", rep_min=8, rep_max=12)
        tools.add_exercise(s, "deadlift", rep_min=3, rep_max=5, increment_kg=5)
        for line in [f"bench press 57.5x10,10,10 {d(14)}", f"bench press 60x8,7,7 {d(10)}",
                     f"bench press 60x9,8,8 {d(7)}", f"squat 100x7,7,7 {d(13)}", f"squat 100x7,7,7 {d(9)}",
                     f"squat 100x7,7,6 {d(5)}", f"db curl 12x12,11,10 {d(8)}", f"db curl 12x12,12,12 {d(2)}"]:
            assert tools.log_workout(s, line, today=TODAY)["status"] == "ok", line
        for meal in ["2 eggs", "1 scoop whey", "pizza"]:
            tools.log_meal(s, meal, today=TODAY)
        tools.set_protein_target(s, 140)


def main() -> int:
    db_path = Path(tempfile.mkdtemp()) / "eval.db"
    engine = storage.get_engine(f"sqlite:///{db_path.as_posix()}")
    SessionLocal = storage.make_session_factory(engine)
    seed(SessionLocal)
    coach = agent.Coach(agent.build_llm(), SessionLocal)

    rows, errors = [], []
    for i, (msg, expected) in enumerate(CASES, 1):
        trace, error = None, None
        for attempt in range(MAX_ATTEMPTS):              # retry network/rate-limit errors, fresh conversation
            try:
                coach.chat(f"eval-{uuid.uuid4()}", msg)
                trace = coach.last_trace
                break
            except Exception as e:
                error = f"{type(e).__name__}: {e}"
                time.sleep(PAUSE_S * 3 * (attempt + 1))
        if trace is None:
            errors.append((msg, error))
            print(f"{i:2d}. ! {msg!r:62} -> API ERROR ({error[:60]})")
            continue
        with SessionLocal() as s:
            memory = tools.memory_context(s)
        first = trace["tools"][0] if trace["tools"] else None
        used = any(t in expected for t in trace["tools"])
        bad = agent.ungrounded_numbers(trace["reply"], trace["tool_outputs"] + [msg, memory, TODAY.isoformat()])
        rows.append({"msg": msg, "expected": expected, "first": first, "tools": trace["tools"],
                     "tool_ok": first in expected, "used": used, "grounded": not bad, "bad": bad,
                     "first_draft": trace["retries"] == 0, "reply": trace["reply"]})
        mark = "✓" if first in expected else ("~" if used else "✗")
        print(f"{i:2d}. {mark} {msg!r:62} -> {' > '.join(trace['tools']) or '(no tool)':40} "
              f"{'grounded' if not bad else 'UNGROUNDED ' + ','.join(bad)}"
              f"{'' if trace['retries'] == 0 else '  (verify rewrote)'}")
        time.sleep(PAUSE_S)

    n = len(rows)
    if not n:
        print("\nEvery case failed on API errors - nothing to score.")
        return 1
    pct = lambda k: f"{100 * sum(r[k] for r in rows) / n:.0f}% ({sum(r[k] for r in rows)}/{n})"
    print(f"\nScored {n}/{len(CASES)} cases ({len(errors)} skipped on API errors).")
    print(f"Tool-selection accuracy (first tool): {pct('tool_ok')}")
    print(f"Expected tool used at all:            {pct('used')}")
    print(f"Replies with no hallucinated numbers: {pct('grounded')}")
    print(f"Grounded on the first draft (verify not needed): {pct('first_draft')}")
    misses = [r for r in rows if not r["tool_ok"]]
    if misses:
        print("\nMisses:")
        for r in misses:
            print(f"  - {r['msg']!r}: expected {'/'.join(r['expected'])}, called {' > '.join(r['tools']) or 'nothing'}"
                  f"  | reply: {r['reply'][:120]!r}")
    engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
