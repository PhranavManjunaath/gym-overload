"""Tests for db.py - storage only; the progression math is tested in test_progression.py."""
import datetime as dt
from pathlib import Path
from typing import Iterator

import pytest
from sqlalchemy.orm import Session

import db
import progression_engine as pe

D1, D2, D3 = dt.date(2026, 10, 20), dt.date(2026, 10, 23), dt.date(2026, 10, 27)


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    engine = db.get_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    with Session(engine) as s:
        yield s
    engine.dispose()


def _sets(weight: float, reps: list, rpe: float = None) -> list:
    return [pe.SetLog(weight, r, rpe) for r in reps]


# ---------- setup ----------

def test_get_engine_creates_folder_and_tables(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "gym.db"
    engine = db.get_engine(f"sqlite:///{path.as_posix()}")
    assert path.exists()
    engine.dispose()


def test_relative_sqlite_path_resolves_to_project_folder() -> None:
    url = db.resolve_database_url("sqlite:///data/gym.db")
    assert Path(url.removeprefix("sqlite:///")) == db.PROJECT_DIR / "data" / "gym.db"
    assert db.resolve_database_url("sqlite:///:memory:") == "sqlite:///:memory:"


@pytest.mark.parametrize("url", [
    "postgresql://postgres.ref:p%40ss@aws-0-x.pooler.supabase.com:5432/postgres",
    "postgres://postgres.ref:p%40ss@aws-0-x.pooler.supabase.com:5432/postgres",
    "postgresql+psycopg://postgres.ref:p%40ss@aws-0-x.pooler.supabase.com:5432/postgres",
    "  postgresql://postgres.ref:p%40ss@aws-0-x.pooler.supabase.com:5432/postgres\n",
])
def test_supabase_url_uses_psycopg_and_keeps_password_untouched(url: str) -> None:
    assert db.resolve_database_url(url) == \
        "postgresql+psycopg://postgres.ref:p%40ss@aws-0-x.pooler.supabase.com:5432/postgres"


def test_describe_engine_hides_password(tmp_path: Path) -> None:
    from sqlalchemy import create_engine
    pg = create_engine(db.resolve_database_url("postgresql://u:secret@host.example:5432/postgres"))
    assert db.describe_engine(pg) == "postgresql at host.example:5432/postgres as u"
    assert "secret" not in db.describe_engine(pg)
    sq = db.get_engine(f"sqlite:///{(tmp_path / 'x.db').as_posix()}")
    assert db.describe_engine(sq).startswith("sqlite file ")
    sq.dispose()


# ---------- exercises ----------

def test_barbell_defaults(session: Session) -> None:
    ex = db.add_exercise(session, "Bench Press")
    assert (ex.name, ex.equipment, ex.rep_min, ex.rep_max, ex.increment, ex.target_sets) == \
        ("bench press", "barbell", 6, 10, 2.5, 3)


def test_dumbbell_default_increment_is_2kg(session: Session) -> None:
    assert db.add_exercise(session, "DB Curl", equipment="dumbbell").increment == 2.0


def test_unknown_equipment_needs_explicit_increment(session: Session) -> None:
    with pytest.raises(ValueError, match="No default increment"):
        db.add_exercise(session, "leg press", equipment="machine")
    assert db.add_exercise(session, "leg press", equipment="machine", increment=5).increment == 5.0


def test_custom_settings(session: Session) -> None:
    ex = db.add_exercise(session, "squat", rep_min=3, rep_max=5, increment=5, target_sets=5)
    assert (ex.rep_min, ex.rep_max, ex.increment, ex.target_sets) == (3, 5, 5.0, 5)


def test_names_are_normalized(session: Session) -> None:
    db.add_exercise(session, "  Bench   Press ")
    assert db.get_exercise(session, "BENCH PRESS") is not None
    with pytest.raises(ValueError, match="already exists"):
        db.add_exercise(session, "bench press")


@pytest.mark.parametrize("kwargs", [
    {"rep_min": 0},
    {"rep_min": 8, "rep_max": 6},
    {"increment": 0},
    {"target_sets": 0},
    {"name": "   "},
])
def test_invalid_exercise_settings_rejected(session: Session, kwargs: dict) -> None:
    args = {"name": "bench press", **kwargs}
    with pytest.raises(ValueError):
        db.add_exercise(session, **args)


def test_get_config_matches_stored_settings(session: Session) -> None:
    db.add_exercise(session, "db curl", equipment="dumbbell", rep_min=8, rep_max=12)
    cfg = db.get_config(session, "db curl")
    assert (cfg.name, cfg.rep_min, cfg.rep_max, cfg.increment, cfg.target_sets) == \
        ("db curl", 8, 12, 2.0, 3)


def test_list_exercises_sorted(session: Session) -> None:
    for n in ["squat", "bench press", "deadlift"]:
        db.add_exercise(session, n)
    assert [e.name for e in db.list_exercises(session)] == ["bench press", "deadlift", "squat"]


# ---------- sessions & history ----------

def test_log_and_read_history(session: Session) -> None:
    db.add_exercise(session, "bench press")
    db.log_session(session, "bench press", D1, _sets(60, [10, 9, 8], rpe=8))
    db.log_session(session, "bench press", D2, _sets(55, [6, 6, 6]), is_deload=True)

    hist = db.get_history(session, "Bench Press")
    assert [h.date for h in hist] == ["2026-10-20", "2026-10-23"]
    assert [(s.weight, s.reps, s.rpe) for s in hist[0].sets] == [(60, 10, 8), (60, 9, 8), (60, 8, 8)]
    assert hist[0].is_deload is False and hist[1].is_deload is True


def test_history_sorted_by_date_even_if_logged_out_of_order(session: Session) -> None:
    db.add_exercise(session, "bench press")
    db.log_session(session, "bench press", D3, _sets(62.5, [6, 6, 6]))
    db.log_session(session, "bench press", D1, _sets(60, [10, 10, 10]))
    assert [h.date for h in db.get_history(session, "bench press")] == ["2026-10-20", "2026-10-27"]


def test_history_is_per_exercise(session: Session) -> None:
    db.add_exercise(session, "bench press")
    db.add_exercise(session, "squat")
    db.log_session(session, "squat", D1, _sets(100, [5, 5, 5]))
    assert db.get_history(session, "bench press") == []
    assert len(db.get_history(session, "squat")) == 1


def test_unknown_exercise_raises(session: Session) -> None:
    with pytest.raises(db.ExerciseNotFound):
        db.log_session(session, "bench press", D1, _sets(60, [10]))
    with pytest.raises(db.ExerciseNotFound):
        db.get_history(session, "bench press")
    with pytest.raises(db.ExerciseNotFound):
        db.get_config(session, "bench press")


@pytest.mark.parametrize("sets", [
    [],
    [pe.SetLog(0, 10)],
    [pe.SetLog(60, -1)],
    [pe.SetLog(60, 10, 11)],
    [pe.SetLog(60, 10, 0.5)],
])
def test_invalid_sets_rejected(session: Session, sets: list) -> None:
    db.add_exercise(session, "bench press")
    with pytest.raises(ValueError):
        db.log_session(session, "bench press", D1, sets)
    assert db.get_history(session, "bench press") == []


def test_data_survives_commit_and_new_session(tmp_path: Path) -> None:
    engine = db.get_engine(f"sqlite:///{(tmp_path / 'gym.db').as_posix()}")
    SessionLocal = db.make_session_factory(engine)
    with SessionLocal.begin() as s:
        db.add_exercise(s, "bench press")
        db.log_session(s, "bench press", D1, _sets(60, [10, 10, 10]))
    with SessionLocal() as s:
        assert len(db.get_history(s, "bench press")) == 1
    engine.dispose()


# ---------- db -> engine hand-off ----------

def test_history_feeds_progression_engine(session: Session) -> None:
    db.add_exercise(session, "bench press")
    db.log_session(session, "bench press", D1, _sets(60, [10, 10, 10]))
    r = pe.next_target(db.get_config(session, "bench press"), db.get_history(session, "bench press"))
    assert (r.action, r.weight, r.target_reps) == ("increase_weight", 62.5, [6, 6, 6])


def test_dumbbell_increment_flows_into_engine(session: Session) -> None:
    db.add_exercise(session, "db curl", equipment="dumbbell", rep_min=8, rep_max=12)
    db.log_session(session, "db curl", D1, _sets(12, [12, 12, 12]))
    r = pe.next_target(db.get_config(session, "db curl"), db.get_history(session, "db curl"))
    assert (r.action, r.weight) == ("increase_weight", 14.0)


def test_no_history_means_engine_asks_for_starting_weight(session: Session) -> None:
    db.add_exercise(session, "bench press")
    with pytest.raises(ValueError, match="starting weight"):
        pe.next_target(db.get_config(session, "bench press"), db.get_history(session, "bench press"))


def test_count_sessions_on(session: Session) -> None:
    db.add_exercise(session, "bench press")
    db.add_exercise(session, "squat")
    assert db.count_sessions_on(session, D1) == 0
    db.log_session(session, "bench press", D1, _sets(60, [10]))
    db.log_session(session, "squat", D1, _sets(100, [5]))
    db.log_session(session, "squat", D2, _sets(100, [5]))
    assert (db.count_sessions_on(session, D1), db.count_sessions_on(session, D2)) == (2, 1)
