"""Tests for progression_engine.py (moved from its old run_tests() function)."""
from typing import List, Optional

import pytest

from progression_engine import (
    ExerciseConfig,
    Session,
    SetLog,
    detect_plateau,
    e1rm_epley,
    next_target,
    round_to_increment,
    volume_load,
)


def _s(date: str, weight: float, reps: List[int], deload: bool = False,
       rpe: Optional[float] = None) -> Session:
    return Session(date, [SetLog(weight, r, rpe) for r in reps], deload)


@pytest.fixture
def cfg() -> ExerciseConfig:
    return ExerciseConfig("bench press", rep_min=6, rep_max=10, increment=2.5)


@pytest.fixture
def plateau_history() -> List[Session]:
    # 62.5 kg, total reps 21, 21, 20 -> no gain over 3 sessions
    return [_s("d1", 62.5, [7, 7, 7]), _s("d2", 62.5, [7, 7, 7]), _s("d3", 62.5, [7, 7, 6])]


# ---------- basic math ----------

def test_e1rm_epley() -> None:
    assert round(e1rm_epley(100, 5), 2) == 116.67
    assert round(e1rm_epley(60, 8), 2) == 76.0
    assert e1rm_epley(80, 1) == 80.0
    assert e1rm_epley(80, 0) == 0.0


def test_round_to_increment() -> None:
    assert round_to_increment(61.3, 2.5) == 62.5
    assert round_to_increment(61.3, 2.5, "down") == 60.0
    assert round_to_increment(57.0, 2.5, "down") == 55.0
    assert round_to_increment(56.25, 2.5, "down") == 55.0
    assert round_to_increment(21.0, 2.0) == 22.0


def test_volume_load() -> None:
    assert volume_load(_s("d", 60, [10, 9, 8])) == 1620


# ---------- rules ----------

def test_increase_weight(cfg: ExerciseConfig) -> None:
    r = next_target(cfg, [_s("d1", 60, [10, 10, 10])])
    assert (r.action, r.weight, r.target_reps) == ("increase_weight", 62.5, [6, 6, 6])


def test_rpe_10_blocks_increase(cfg: ExerciseConfig) -> None:
    r = next_target(cfg, [_s("d1", 60, [10, 10, 10], rpe=10)])
    assert r.action == "add_reps" and r.weight == 60


def test_add_reps(cfg: ExerciseConfig) -> None:
    r = next_target(cfg, [_s("d1", 60, [10, 9, 8])])
    assert (r.action, r.weight, r.target_reps) == ("add_reps", 60, [10, 10, 9])


def test_first_failure_repeats(cfg: ExerciseConfig) -> None:
    r = next_target(cfg, [_s("d1", 60, [7, 6, 5])])
    assert (r.action, r.weight) == ("repeat", 60)


def test_two_failures_reduce_weight(cfg: ExerciseConfig) -> None:
    # 60 * 0.95 = 57 -> rounded down to 55
    r = next_target(cfg, [_s("d1", 60, [7, 6, 5]), _s("d2", 60, [6, 5, 5])])
    assert (r.action, r.weight) == ("reduce_weight", 55.0)


def test_plateau_triggers_deload(cfg: ExerciseConfig, plateau_history: List[Session]) -> None:
    # deload 62.5 * 0.9 = 56.25 -> rounded down to 55
    assert detect_plateau(cfg, plateau_history)
    r = next_target(cfg, plateau_history)
    assert (r.action, r.weight) == ("deload", 55.0)


def test_no_plateau_if_reps_went_up(cfg: ExerciseConfig) -> None:
    hist = [_s("d1", 62.5, [7, 7, 7]), _s("d2", 62.5, [8, 7, 7]), _s("d3", 62.5, [7, 7, 7])]
    assert not detect_plateau(cfg, hist)


def test_resume_after_deload(cfg: ExerciseConfig, plateau_history: List[Session]) -> None:
    hist = plateau_history + [_s("d4", 55, [6, 6, 6], deload=True)]
    r = next_target(cfg, hist)
    assert (r.action, r.weight) == ("resume", 62.5)
    # no immediate re-plateau after resuming
    hist.append(_s("d5", 62.5, [8, 7, 7]))
    assert not detect_plateau(cfg, hist)


def test_dumbbell_2kg_increment() -> None:
    db = ExerciseConfig("db curl", rep_min=8, rep_max=12, increment=2.0)
    r = next_target(db, [_s("d1", 12, [12, 12, 12])])
    assert (r.action, r.weight, r.target_reps) == ("increase_weight", 14.0, [8, 8, 8])
