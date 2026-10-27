"""Tests for parser.py - workout text in, exact structured data out."""
import datetime as dt
from typing import List, Optional, Tuple

import pytest

import parser as wp
import progression_engine as pe

TODAY = dt.date(2026, 10, 27)


def _one(text: str) -> wp.ParsedEntry:
    entries = wp.parse_message(text, today=TODAY)
    assert len(entries) == 1
    return entries[0]


def _sets(entry: wp.ParsedEntry) -> List[Tuple[float, int, Optional[float]]]:
    return [(s.weight, s.reps, s.rpe) for s in entry.sets]


# ---------- basic formats ----------

def test_simple_line() -> None:
    e = _one("bench 60x10,10,9")
    assert (e.exercise, e.date, e.is_deload) == ("bench", TODAY, False)
    assert _sets(e) == [(60.0, 10, None), (60.0, 10, None), (60.0, 9, None)]


@pytest.mark.parametrize("text", [
    "bench 60x10,10,9",
    "Bench 60kg x 10, 10, 9",
    "BENCH 60 X 10,10,9",
    "bench 60×10,10,9",
    "bench 60*10,10,9",
    "bench 60 kg x 10 , 10 , 9",
    "Bench: 60x10,10,9",
])
def test_spacing_case_and_symbols_dont_matter(text: str) -> None:
    e = _one(text)
    assert e.exercise == "bench"
    assert _sets(e) == [(60.0, 10, None), (60.0, 10, None), (60.0, 9, None)]


def test_multi_word_exercise_name() -> None:
    assert _one("Incline  DB  Press 22x10,9").exercise == "incline db press"


def test_name_with_x_is_not_mangled() -> None:
    assert _one("box squat 80x5,5").exercise == "box squat"


def test_decimal_weight() -> None:
    assert _sets(_one("bench 62.5x8"))[0] == (62.5, 8, None)


def test_different_weights_per_group() -> None:
    e = _one("bench 60x10 62.5x8,7")
    assert _sets(e) == [(60.0, 10, None), (62.5, 8, None), (62.5, 7, None)]


def test_zero_rep_set_is_kept() -> None:
    assert _sets(_one("bench 60x6,5,0"))[-1] == (60.0, 0, None)


# ---------- RPE ----------

def test_rpe_per_set() -> None:
    e = _one("bench 60x10@8,10@8.5,9@9")
    assert _sets(e) == [(60.0, 10, 8.0), (60.0, 10, 8.5), (60.0, 9, 9.0)]


def test_line_rpe_applies_to_all_sets() -> None:
    e = _one("bench 60x10,10,9 @8")
    assert [s.rpe for s in e.sets] == [8.0, 8.0, 8.0]


def test_line_rpe_with_space_after_at() -> None:
    assert [s.rpe for s in _one("bench 60x10,10 @ 9").sets] == [9.0, 9.0]


def test_per_set_rpe_wins_over_line_rpe() -> None:
    assert [s.rpe for s in _one("bench 60x10,10,9@9.5 @8").sets] == [8.0, 8.0, 9.5]


# ---------- deload & dates ----------

def test_deload_flag() -> None:
    assert _one("squat 100x5,5,5 deload").is_deload is True
    assert _one("deload squat 100x5,5,5").exercise == "squat"


@pytest.mark.parametrize("text, expected", [
    ("squat 100x5 yesterday", dt.date(2026, 10, 26)),
    ("squat 100x5 today", TODAY),
    ("2026-10-20 squat 100x5", dt.date(2026, 10, 20)),
    ("squat 100x5 2026-10-20", dt.date(2026, 10, 20)),
])
def test_dates(text: str, expected: dt.date) -> None:
    assert _one(text).date == expected


def test_default_date_is_today() -> None:
    assert wp.parse_message("bench 60x10")[0].date == dt.date.today()


# ---------- several exercises ----------

def test_multiple_lines_and_semicolons() -> None:
    entries = wp.parse_message("bench 60x10,10,9\n\nsquat 100x5,5,5; db curl 12x12,11", today=TODAY)
    assert [e.exercise for e in entries] == ["bench", "squat", "db curl"]
    assert _sets(entries[2]) == [(12.0, 12, None), (12.0, 11, None)]


# ---------- errors: never guess ----------

@pytest.mark.parametrize("text, msg", [
    ("", "Empty message"),
    ("   \n ; ", "Empty message"),
    ("bench", "no sets"),
    ("60x10,10,9", "missing exercise name"),
    ("bench 60x10 squat", "couldn't read 'squat'"),
    ("bench 60x10.5", "couldn't read"),
    ("bench 60x", "couldn't read"),
    ("bench 60", "couldn't read"),
    ("bench 62,5x10", "couldn't read"),
    ("bench 135lbs x 10", "kg"),
    ("bench 135 lb x 10", "kg"),
    ("bench 60x10 @8 @9", "more than one line RPE"),
    ("bench 60x10 yesterday 2026-10-20", "more than one date"),
    ("bench 60x10 2026-02-30", "isn't a real date"),
    ("bench 60x10 2026-10-28", "in the future"),
])
def test_bad_input_raises_clear_error(text: str, msg: str) -> None:
    with pytest.raises(wp.ParseError, match=msg):
        wp.parse_message(text, today=TODAY)


def test_one_bad_line_rejects_whole_message() -> None:
    with pytest.raises(wp.ParseError, match="squat"):
        wp.parse_message("bench 60x10,10,9\nsquat 100", today=TODAY)


# ---------- hand-off to the engine ----------

def test_parsed_sets_feed_progression_engine() -> None:
    e = _one("bench 60x10,10,10 @8")
    cfg = pe.ExerciseConfig("bench", rep_min=6, rep_max=10, increment=2.5)
    r = pe.next_target(cfg, [pe.Session(e.date.isoformat(), e.sets, e.is_deload)])
    assert (r.action, r.weight) == ("increase_weight", 62.5)
