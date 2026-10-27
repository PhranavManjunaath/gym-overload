"""
Database layer - SQLite via SQLAlchemy.

Stores exercises (with their progression settings), workout sessions and sets.
No progression math happens here: get_history() turns stored rows into
progression_engine.Session objects, and the engine does the rest.

Transactions: helpers only flush(); the caller commits, e.g.
    SessionLocal = make_session_factory(get_engine())
    with SessionLocal.begin() as db:
        log_session(db, "bench press", date.today(), sets)
"""
from __future__ import annotations

import datetime as dt
import os
from pathlib import Path
from typing import List, Optional, Sequence

from dotenv import load_dotenv
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    create_engine,
    event,
    make_url,
    select,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    relationship,
    sessionmaker,
)

import progression_engine as pe

PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_DATABASE_URL = "sqlite:///data/gym.db"

# Defaults from CLAUDE.md: 6-10 reps, 3 sets, 2.5 kg barbell, 2 kg dumbbell.
_ENGINE_DEFAULTS = pe.ExerciseConfig("_")
DEFAULT_INCREMENTS = {"barbell": 2.5, "dumbbell": 2.0}


class ExerciseNotFound(LookupError):
    """The exercise hasn't been set up yet - ask the user to add it."""


# ---------- tables ----------

class Base(DeclarativeBase):
    pass


class Exercise(Base):
    __tablename__ = "exercises"
    __table_args__ = (
        CheckConstraint("rep_min >= 1", name="rep_min_positive"),
        CheckConstraint("rep_max >= rep_min", name="rep_range_valid"),
        CheckConstraint("increment > 0", name="increment_positive"),
        CheckConstraint("target_sets >= 1", name="target_sets_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)   # normalized, e.g. "bench press"
    equipment: Mapped[str] = mapped_column(String(30))
    rep_min: Mapped[int] = mapped_column(Integer)
    rep_max: Mapped[int] = mapped_column(Integer)
    increment: Mapped[float] = mapped_column(Float)               # kg
    target_sets: Mapped[int] = mapped_column(Integer)

    sessions: Mapped[List[WorkoutSession]] = relationship(
        back_populates="exercise", cascade="all, delete-orphan"
    )


class WorkoutSession(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    exercise_id: Mapped[int] = mapped_column(ForeignKey("exercises.id", ondelete="CASCADE"))
    date: Mapped[dt.date] = mapped_column(Date)
    is_deload: Mapped[bool] = mapped_column(Boolean, default=False)

    exercise: Mapped[Exercise] = relationship(back_populates="sessions")
    sets: Mapped[List[SetEntry]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="SetEntry.set_number"
    )


class SetEntry(Base):
    __tablename__ = "sets"
    __table_args__ = (
        UniqueConstraint("session_id", "set_number", name="one_row_per_set"),
        CheckConstraint("weight > 0", name="weight_positive"),
        CheckConstraint("reps >= 0", name="reps_not_negative"),
        CheckConstraint("rpe IS NULL OR (rpe >= 1 AND rpe <= 10)", name="rpe_range"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"))
    set_number: Mapped[int] = mapped_column(Integer)              # 1, 2, 3 ...
    weight: Mapped[float] = mapped_column(Float)                  # kg
    reps: Mapped[int] = mapped_column(Integer)
    rpe: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    session: Mapped[WorkoutSession] = relationship(back_populates="sets")


# ---------- engine / sessions ----------

def resolve_database_url(url: str) -> str:
    """
    - Postgres URLs as Supabase gives them (postgresql://, postgres://) -> use the psycopg driver.
    - A relative SQLite path -> relative to the project folder, not the current directory.
    """
    url = url.strip()
    # String replace, not make_url(): rendering a URL can re-encode the password.
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    u = make_url(url)
    if u.get_backend_name() != "sqlite" or not u.database or u.database == ":memory:":
        return url
    path = Path(u.database)
    if not path.is_absolute():
        path = PROJECT_DIR / path
    # Built by hand: URL.render_as_string() percent-encodes Windows paths (C%3A%5C...).
    return f"sqlite:///{path.as_posix()}"


@event.listens_for(Engine, "connect")
def _sqlite_foreign_keys_on(dbapi_conn, _record) -> None:  # type: ignore[no-untyped-def]
    # SQLite ignores foreign keys unless this is switched on for every connection.
    if type(dbapi_conn).__module__.startswith("sqlite3"):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()


def get_engine(url: Optional[str] = None) -> Engine:
    """Connect to the database (DATABASE_URL from .env by default) and create tables if missing."""
    if url is None:
        load_dotenv(PROJECT_DIR / ".env")
        url = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)
    url = resolve_database_url(url)
    u = make_url(url)
    if u.get_backend_name() == "sqlite":
        if u.database and u.database != ":memory:":
            Path(u.database).parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(url)
    else:
        # pool_pre_ping: reconnect if the hosted DB (e.g. Supabase) dropped an idle connection.
        engine = create_engine(url, pool_pre_ping=True)
    Base.metadata.create_all(engine)
    return engine


def describe_engine(engine: Engine) -> str:
    """Where we're connected, without the password - safe to print or log."""
    u = engine.url
    if u.get_backend_name() == "sqlite":
        return f"sqlite file {u.database}"
    return f"{u.get_backend_name()} at {u.host}:{u.port}/{u.database} as {u.username}"


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


# ---------- exercises ----------

def normalize_name(name: str) -> str:
    """'  Bench   Press ' -> 'bench press', so the same lift always matches."""
    return " ".join(name.strip().lower().split())


def get_exercise(db: Session, name: str) -> Optional[Exercise]:
    return db.scalar(select(Exercise).where(Exercise.name == normalize_name(name)))


def _require_exercise(db: Session, name: str) -> Exercise:
    ex = get_exercise(db, name)
    if ex is None:
        raise ExerciseNotFound(f"No exercise called '{normalize_name(name)}' - add it first.")
    return ex


def add_exercise(
    db: Session,
    name: str,
    equipment: str = "barbell",
    rep_min: Optional[int] = None,
    rep_max: Optional[int] = None,
    increment: Optional[float] = None,
    target_sets: Optional[int] = None,
) -> Exercise:
    key = normalize_name(name)
    equipment = normalize_name(equipment)
    if not key:
        raise ValueError("Exercise name can't be empty.")
    if get_exercise(db, key) is not None:
        raise ValueError(f"Exercise '{key}' already exists.")

    if increment is None:
        if equipment not in DEFAULT_INCREMENTS:
            # Never guess: only barbell and dumbbell have a known default jump.
            raise ValueError(
                f"No default increment for '{equipment}' - give the smallest weight jump in kg."
            )
        increment = DEFAULT_INCREMENTS[equipment]
    rep_min = _ENGINE_DEFAULTS.rep_min if rep_min is None else rep_min
    rep_max = _ENGINE_DEFAULTS.rep_max if rep_max is None else rep_max
    target_sets = _ENGINE_DEFAULTS.target_sets if target_sets is None else target_sets

    if rep_min < 1:
        raise ValueError("rep_min must be at least 1.")
    if rep_max < rep_min:
        raise ValueError("rep_max must be >= rep_min.")
    if increment <= 0:
        raise ValueError("increment must be more than 0 kg.")
    if target_sets < 1:
        raise ValueError("target_sets must be at least 1.")

    ex = Exercise(name=key, equipment=equipment, rep_min=rep_min, rep_max=rep_max,
                  increment=float(increment), target_sets=target_sets)
    db.add(ex)
    db.flush()
    return ex


def list_exercises(db: Session) -> List[Exercise]:
    return list(db.scalars(select(Exercise).order_by(Exercise.name)))


def get_config(db: Session, name: str) -> pe.ExerciseConfig:
    """The exercise's settings in the form progression_engine expects."""
    ex = _require_exercise(db, name)
    return pe.ExerciseConfig(ex.name, rep_min=ex.rep_min, rep_max=ex.rep_max,
                             increment=ex.increment, target_sets=ex.target_sets)


# ---------- sessions ----------

def log_session(
    db: Session,
    exercise_name: str,
    date: dt.date,
    sets: Sequence[pe.SetLog],
    is_deload: bool = False,
) -> WorkoutSession:
    """Save one workout of one exercise. `sets` are working sets only, in order."""
    ex = _require_exercise(db, exercise_name)
    if not sets:
        raise ValueError("A session needs at least one working set.")
    for i, s in enumerate(sets, start=1):
        if s.weight <= 0:
            raise ValueError(f"Set {i}: weight must be more than 0 kg.")
        if not isinstance(s.reps, int) or s.reps < 0:
            raise ValueError(f"Set {i}: reps must be a whole number, 0 or more.")
        if s.rpe is not None and not 1 <= s.rpe <= 10:
            raise ValueError(f"Set {i}: RPE must be between 1 and 10.")

    ws = WorkoutSession(
        exercise=ex,
        date=date,
        is_deload=is_deload,
        sets=[SetEntry(set_number=i, weight=float(s.weight), reps=s.reps, rpe=s.rpe)
              for i, s in enumerate(sets, start=1)],
    )
    db.add(ws)
    db.flush()
    return ws


def get_history(db: Session, exercise_name: str) -> List[pe.Session]:
    """All sessions for an exercise, oldest first, as progression_engine objects."""
    ex = _require_exercise(db, exercise_name)
    rows = db.scalars(
        select(WorkoutSession)
        .where(WorkoutSession.exercise_id == ex.id)
        .order_by(WorkoutSession.date, WorkoutSession.id)
    )
    return [
        pe.Session(r.date.isoformat(), [pe.SetLog(s.weight, s.reps, s.rpe) for s in r.sets], r.is_deload)
        for r in rows
    ]


# ---------- connection check (run: python db.py) ----------

if __name__ == "__main__":
    from sqlalchemy import inspect

    eng = get_engine()
    print("Connected:", describe_engine(eng))
    print("Tables:", ", ".join(sorted(inspect(eng).get_table_names())))
