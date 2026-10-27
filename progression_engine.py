"""
Progression engine - reference implementation for the Gym Progressive-Overload Agent.
All numbers are computed here in plain Python. The LLM never does the math;
it only calls these functions as tools and explains the result.

Method: double progression
  - Each exercise has a rep range [rep_min, rep_max] and a weight increment.
  - Hit rep_max on ALL working sets (RPE <= 9 if logged) -> add one increment, reset to rep_min.
  - All sets >= rep_min but not all at rep_max -> same weight, +1 rep on sets below rep_max.
  - Any set < rep_min -> repeat the weight. Two failed sessions in a row at the same weight
    -> drop ~5% (rounded DOWN to the increment).
  - Plateau: 3 sessions in a row at the same weight with no gain in total reps
    -> deload to 90% (rounded DOWN), then resume at the pre-deload weight.
"""
from dataclasses import dataclass, field
from typing import List, Optional
import math

EPS = 1e-9


@dataclass
class SetLog:
    weight: float          # kg on the bar/dumbbell
    reps: int
    rpe: Optional[float] = None


@dataclass
class Session:
    date: str              # ISO date "2026-10-27"
    sets: List[SetLog]     # working sets only (no warm-ups)
    is_deload: bool = False


@dataclass
class ExerciseConfig:
    name: str
    rep_min: int = 6
    rep_max: int = 10
    increment: float = 2.5     # smallest jump you can actually load
    target_sets: int = 3
    max_rpe_for_increase: float = 9.0
    plateau_window: int = 3
    deload_pct: float = 0.90
    failure_drop_pct: float = 0.95


@dataclass
class Recommendation:
    action: str                    # increase_weight | add_reps | repeat | reduce_weight | deload | resume
    weight: float
    target_reps: List[int]
    reason: str
    e1rm_last: float = 0.0
    details: dict = field(default_factory=dict)


# ---------- basic math ----------

def e1rm_epley(weight: float, reps: int) -> float:
    """Estimated 1-rep max (Epley). 1 rep -> the weight itself. Unreliable above 12 reps."""
    if reps <= 0 or weight <= 0:
        return 0.0
    if reps == 1:
        return float(weight)
    return weight * (1 + reps / 30)


def round_to_increment(weight: float, increment: float, mode: str = "nearest") -> float:
    q = weight / increment
    if mode == "down":
        q = math.floor(q + EPS)
    elif mode == "up":
        q = math.ceil(q - EPS)
    else:
        q = math.floor(q + 0.5)
    return round(q * increment, 2)


def volume_load(session: Session) -> float:
    return sum(s.weight * s.reps for s in session.sets)


def total_reps(session: Session) -> int:
    return sum(s.reps for s in session.sets)


def working_weight(session: Session) -> float:
    return max(s.weight for s in session.sets)


def best_e1rm(session: Session) -> float:
    valid = [s for s in session.sets if s.reps <= 12] or session.sets
    return round(max(e1rm_epley(s.weight, s.reps) for s in valid), 2)


# ---------- rules ----------

def _is_failure(cfg: ExerciseConfig, s: Session) -> bool:
    return any(x.reps < cfg.rep_min for x in s.sets)


def _sessions_since_deload(history: List[Session]) -> List[Session]:
    out = []
    for s in reversed(history):
        if s.is_deload:
            break
        out.append(s)
    return list(reversed(out))


def detect_plateau(cfg: ExerciseConfig, history: List[Session]) -> bool:
    recent = _sessions_since_deload(history)
    w = cfg.plateau_window
    if len(recent) < w:
        return False
    window = recent[-w:]
    if len({working_weight(s) for s in window}) != 1:
        return False
    first = total_reps(window[0])
    return all(total_reps(s) <= first for s in window[1:])


def next_target(cfg: ExerciseConfig, history: List[Session]) -> Recommendation:
    if not history:
        raise ValueError("No history for this exercise - ask the user for a starting weight.")
    last = history[-1]
    w = working_weight(last)
    e1 = best_e1rm(last)

    # 1) coming back from a deload -> resume the weight used before it
    if last.is_deload:
        prev = [s for s in history[:-1] if not s.is_deload]
        resume_w = working_weight(prev[-1]) if prev else w
        return Recommendation("resume", resume_w, [cfg.rep_min] * cfg.target_sets,
                              "Deload done - back to your pre-deload weight.", e1)

    # 2) two failed sessions in a row at the same weight -> drop ~5%
    if len(history) >= 2:
        prev = history[-2]
        if (_is_failure(cfg, last) and _is_failure(cfg, prev)
                and not prev.is_deload and working_weight(prev) == w):
            new_w = round_to_increment(w * cfg.failure_drop_pct, cfg.increment, "down")
            return Recommendation("reduce_weight", new_w, [cfg.rep_min] * cfg.target_sets,
                                  f"Missed {cfg.rep_min} reps two sessions in a row at {w} kg.", e1)

    # 3) plateau -> deload
    if detect_plateau(cfg, history):
        new_w = round_to_increment(w * cfg.deload_pct, cfg.increment, "down")
        return Recommendation("deload", new_w, [cfg.rep_min] * cfg.target_sets,
                              f"No rep gain in {cfg.plateau_window} sessions at {w} kg - one light session.",
                              e1, {"plateau": True})

    reps = [s.reps for s in last.sets]
    rpes = [s.rpe for s in last.sets if s.rpe is not None]
    rpe_ok = all(r <= cfg.max_rpe_for_increase for r in rpes)

    # 4) all sets at top of range -> add weight
    if len(reps) >= cfg.target_sets and all(r >= cfg.rep_max for r in reps) and rpe_ok:
        return Recommendation("increase_weight", round(w + cfg.increment, 2),
                              [cfg.rep_min] * cfg.target_sets,
                              f"Hit {cfg.rep_max} reps on all sets - add {cfg.increment} kg.", e1)

    # 5) inside the range -> add reps
    if all(r >= cfg.rep_min for r in reps):
        targets = [min(r + 1, cfg.rep_max) for r in reps]
        targets += [cfg.rep_min] * (cfg.target_sets - len(targets))
        return Recommendation("add_reps", w, targets,
                              "Same weight - beat last session by 1 rep on each set below the top.", e1)

    # 6) first failure -> repeat
    return Recommendation("repeat", w, [cfg.rep_min] * cfg.target_sets,
                          f"Some sets under {cfg.rep_min} reps - repeat {w} kg.", e1)
