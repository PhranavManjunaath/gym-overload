"""Tests for analytics.py with fake dates - streaks, missed workouts, consistency, milestones, summaries."""
import datetime as dt

import pytest

import analytics as an
import progression_engine as pe

MWF = ["mon", "wed", "fri"]
D = lambda s: dt.date.fromisoformat(s)
# Oct 2026: Mon 19, Wed 21, Fri 23, Mon 26, Tue 27, Wed 28
MON19, WED21, FRI23, MON26, TUE27, WED28 = map(D, ["2026-10-19", "2026-10-21", "2026-10-23",
                                                   "2026-10-26", "2026-10-27", "2026-10-28"])


def _s(date: str, weight: float, reps: list, deload: bool = False) -> pe.Session:
    return pe.Session(date, [pe.SetLog(weight, r) for r in reps], deload)


# ---------- missed workout ----------

def test_missed_workout_only_on_unlogged_training_day() -> None:
    assert an.missed_workout(MWF, set(), MON26)
    assert not an.missed_workout(MWF, {MON26}, MON26)
    assert not an.missed_workout(MWF, set(), TUE27)            # rest day: no nudge


# ---------- streaks ----------

def test_streak_counts_consecutive_completed_training_days() -> None:
    logged = {MON19, WED21, FRI23, MON26}
    assert an.current_streak(MWF, logged, MON26) == 4


def test_unlogged_today_does_not_break_streak() -> None:
    logged = {MON19, WED21, FRI23}
    assert an.current_streak(MWF, logged, MON26) == 3          # Monday not over yet
    assert an.current_streak(MWF, logged, TUE27) == 0          # Monday was missed


def test_missed_day_breaks_streak() -> None:
    logged = {MON19, FRI23, MON26}                             # Wednesday missed
    assert an.current_streak(MWF, logged, MON26) == 2


def test_rest_day_logs_neither_count_nor_break() -> None:
    logged = {MON19, WED21, D("2026-10-22"), FRI23}            # extra Thursday session
    assert an.current_streak(MWF, logged, D("2026-10-24")) == 3


def test_streak_on_rest_day_counts_back_from_last_training_day() -> None:
    assert an.current_streak(MWF, {MON19, WED21, FRI23, MON26}, TUE27) == 4


def test_streak_empty_cases() -> None:
    assert an.current_streak(MWF, set(), MON26) == 0
    assert an.current_streak([], {MON26}, MON26) == 0


def test_best_streak() -> None:
    logged = {MON19, WED21, FRI23, WED28}                      # Mon 26 missed
    assert an.best_streak(MWF, logged, WED28) == 3
    assert an.current_streak(MWF, logged, WED28) == 1


# ---------- consistency ----------

def test_consistency_since_first_log() -> None:
    c = an.consistency(MWF, {MON19, FRI23, MON26}, TUE27)
    assert (c["done"], c["planned"], c["percent"]) == (3, 4, 75)   # Mon, Wed, Fri, Mon


def test_consistency_ignores_unlogged_today() -> None:
    c = an.consistency(MWF, {MON19, WED21, FRI23}, MON26)
    assert (c["done"], c["planned"], c["percent"]) == (3, 3, 100)


def test_consistency_empty() -> None:
    assert an.consistency(MWF, set(), MON26)["percent"] is None


# ---------- milestones ----------

def test_new_e1rm_best_is_a_milestone() -> None:
    old = _s("2026-10-19", 60, [10, 10, 10])                   # e1RM 80
    new = _s("2026-10-21", 65, [8, 8, 8])                      # 65 * (1 + 8/30) = 82.33
    m = an.e1rm_milestone([old, new], new)
    assert m == {"e1rm_kg": 82.33, "previous_best_kg": 80.0, "gain_kg": 2.33}


def test_no_milestone_when_equal_lower_or_first() -> None:
    old = _s("2026-10-19", 60, [10, 10, 10])
    same = _s("2026-10-21", 60, [10, 9, 8])
    assert an.e1rm_milestone([old, same], same) is None
    assert an.e1rm_milestone([old], old) is None


# ---------- summaries ----------

def test_progress_summary() -> None:
    history = [_s("2026-09-01", 50, [10]), _s("2026-10-19", 60, [10, 9, 8]), _s("2026-10-26", 62.5, [8, 7, 6])]
    r = an.progress_summary(history, TUE27, weeks=2)
    assert (r["sessions"], r["first_date"], r["last_date"]) == (2, "2026-10-19", "2026-10-26")
    assert (r["e1rm_first_kg"], r["e1rm_last_kg"], r["e1rm_change_kg"]) == (80.0, 79.17, -0.83)
    assert (r["volume_first_kg"], r["volume_last_kg"], r["volume_change_kg"]) == (1620.0, 1312.5, -307.5)
    assert r["total_volume_kg"] == 2932.5
    assert r["best_set"] == {"date": "2026-10-19", "weight_kg": 60, "reps": 10, "e1rm_kg": 80.0}


def test_progress_summary_empty_window() -> None:
    r = an.progress_summary([_s("2026-01-01", 50, [10])], TUE27, weeks=4)
    assert r["sessions"] == 0 and "e1rm_last_kg" not in r


def test_best_set_ignores_high_rep_sets() -> None:
    assert an.best_set([_s("2026-10-19", 40, [20]), _s("2026-10-20", 50, [5])])["weight_kg"] == 50


@pytest.mark.parametrize("day, mon, sun", [("2026-10-27", "2026-10-26", "2026-11-01"),
                                           ("2026-11-01", "2026-10-26", "2026-11-01")])
def test_week_bounds(day: str, mon: str, sun: str) -> None:
    assert an.week_bounds(D(day)) == (D(mon), D(sun))
