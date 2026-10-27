"""Tests for reports.py - weekly numbers from Python, LLM summary only if every number is real, CSV export."""
import csv
import datetime as dt
import io
from pathlib import Path
from typing import Iterator

import pytest
from sqlalchemy.orm import Session

import db as storage
import reports
import tools

SUN = dt.date(2026, 11, 1)          # week Mon 26 Oct - Sun 1 Nov


@pytest.fixture
def session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Session]:
    for k in ["WORKOUT_DAYS", "WORKOUT_REMINDER_TIME"]:
        monkeypatch.delenv(k, raising=False)
    engine = storage.get_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    with storage.make_session_factory(engine)() as s:
        tools.add_exercise(s, "bench")
        tools.add_exercise(s, "squat")
        for line in ["bench 60x10,10,10 2026-10-21",                       # last week: e1RM 80
                     "bench 62.5x8,8,8 2026-10-26", "bench 62.5x9,8,8 2026-10-28",   # this week: 81.25
                     "squat 100x5,5,5 deload 2026-10-30"]:
            assert tools.log_workout(s, line, today=SUN)["status"] == "ok"
        tools.set_protein_target(s, 100)
        tools.log_meal(s, "chicken breast 400g", today=dt.date(2026, 10, 27))     # 124 g - on target
        tools.log_meal(s, "2 eggs", today=dt.date(2026, 10, 28))                  # 12 g - below
        s.commit()
        yield s
    engine.dispose()


def test_weekly_stats(session: Session) -> None:
    st = reports.weekly_stats(session, SUN)
    assert st["week"] == "2026-10-26 to 2026-11-01"
    assert (st["training_days_planned"], st["training_days_done"], st["sessions_logged"]) == (3, 3, 3)
    assert st["total_volume_kg"] == 4562.5                  # 62.5×24 + 62.5×25 + 100×15
    bench, squat = st["lifts"]
    assert (bench["best_e1rm_kg"], bench["previous_week_best_e1rm_kg"], bench["change_kg"]) == (81.25, 80.0, 1.25)
    assert (squat["deload"], squat["change_kg"]) == (True, None)
    assert st["protein"] == {"on_target": 1, "days": 7, "target_g": 100.0}


def test_stats_text_has_every_number(session: Session) -> None:
    text = reports.stats_text(reports.weekly_stats(session, SUN))
    assert "Training days: 3/3 planned" in text
    assert "• bench: best e1RM 81.25 kg (+1.25 kg vs last week)" in text
    assert "• squat: best e1RM 116.67 kg (no sessions last week) · deload week" in text
    assert "Protein: 1/7 days at or above your 100 g target" in text


def test_summary_kept_only_if_numbers_are_real(session: Session) -> None:
    good = reports.weekly_report(session, SUN, summarize=lambda p: "3 of 3 training days done - great week!")
    assert good.startswith("3 of 3 training days done")
    bad = reports.weekly_report(session, SUN, summarize=lambda p: "You lifted 9000 kg this week!")
    assert bad.startswith("📅 Week")                         # invented number -> summary dropped
    def boom(p: str) -> str:
        raise RuntimeError("Groq down")
    assert reports.weekly_report(session, SUN, summarize=boom).startswith("📅 Week")


def test_empty_week(session: Session) -> None:
    text = reports.stats_text(reports.weekly_stats(session, dt.date(2026, 12, 6)))
    assert "No sessions logged this week." in text


def test_export_workouts_csv(session: Session) -> None:
    rows = list(csv.DictReader(io.StringIO(reports.export_workouts_csv(session))))
    assert len(rows) == 12
    assert rows[0] == {"date": "2026-10-21", "exercise": "bench", "set": "1", "weight_kg": "60.0", "reps": "10",
                       "rpe": "", "deload": "False"}
    assert rows[-1]["exercise"] == "squat" and rows[-1]["deload"] == "True"


def test_export_meals_csv(session: Session) -> None:
    rows = list(csv.DictReader(io.StringIO(reports.export_meals_csv(session))))
    assert [(r["text"], r["protein_g"], r["protein_estimated"]) for r in rows] == \
        [("chicken breast 400g", "124.0", "True"), ("2 eggs", "12.0", "True")]
