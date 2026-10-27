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
from typing import Any, Dict, List, Optional, Sequence, Set

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
    func,
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
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


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


class Preference(Base):
    """Long-term memory the agent sees every turn, e.g. 'dislikes' -> 'lunges'."""
    __tablename__ = "preferences"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(100), unique=True)
    value: Mapped[str] = mapped_column(String(500))


class Setting(Base):
    """App settings set by the user: goal, protein target, training days, reminder time."""
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[str] = mapped_column(String(500))


class DayPlan(Base):
    """Which exercises are trained on which weekday (for that day's reminder)."""
    __tablename__ = "day_plan"
    __table_args__ = (UniqueConstraint("day", "exercise_id", name="one_exercise_per_day"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    day: Mapped[str] = mapped_column(String(3))                   # mon..sun
    exercise_id: Mapped[int] = mapped_column(ForeignKey("exercises.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer, default=0)

    exercise: Mapped[Exercise] = relationship()


class Meal(Base):
    __tablename__ = "meals"
    __table_args__ = (CheckConstraint("protein_g IS NULL OR protein_g >= 0", name="protein_not_negative"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[dt.date] = mapped_column(Date)
    text: Mapped[str] = mapped_column(String(500))
    protein_g: Mapped[Optional[float]] = mapped_column(Float, nullable=True)   # None = unknown, ask the user
    protein_estimated: Mapped[bool] = mapped_column(Boolean, default=True)     # False once the user confirms/corrects


class Notification(Base):
    """Every proactive message sent - for the 2-per-day cap and 'send only once' rules."""
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[dt.date] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(String(40))


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


def database_url() -> str:
    """DATABASE_URL from the environment, else .env, else the local SQLite file."""
    load_dotenv(PROJECT_DIR / ".env")          # never overrides a variable that's already set
    return resolve_database_url(os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL))


def get_engine(url: Optional[str] = None) -> Engine:
    """Connect to the database (DATABASE_URL from .env by default) and create tables if missing."""
    url = database_url() if url is None else resolve_database_url(url)
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
    _validate_settings(rep_min, rep_max, increment, target_sets)

    ex = Exercise(name=key, equipment=equipment, rep_min=rep_min, rep_max=rep_max,
                  increment=float(increment), target_sets=target_sets)
    db.add(ex)
    db.flush()
    return ex


def _validate_settings(rep_min: int, rep_max: int, increment: float, target_sets: int) -> None:
    if rep_min < 1:
        raise ValueError("rep_min must be at least 1.")
    if rep_max < rep_min:
        raise ValueError("rep_max must be >= rep_min.")
    if increment <= 0:
        raise ValueError("increment must be more than 0 kg.")
    if target_sets < 1:
        raise ValueError("target_sets must be at least 1.")


def update_exercise_settings(
    db: Session,
    name: str,
    rep_min: Optional[int] = None,
    rep_max: Optional[int] = None,
    increment: Optional[float] = None,
    target_sets: Optional[int] = None,
) -> Exercise:
    """Change an exercise's progression settings; anything left as None stays the same."""
    ex = _require_exercise(db, name)
    new = (
        ex.rep_min if rep_min is None else rep_min,
        ex.rep_max if rep_max is None else rep_max,
        ex.increment if increment is None else float(increment),
        ex.target_sets if target_sets is None else target_sets,
    )
    _validate_settings(*new)
    ex.rep_min, ex.rep_max, ex.increment, ex.target_sets = new
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


def count_sessions_on(db: Session, date: dt.date) -> int:
    """How many exercise sessions were logged on a date (any exercise) - for reminders."""
    return db.scalar(select(func.count(WorkoutSession.id)).where(WorkoutSession.date == date)) or 0


def session_dates(db: Session) -> Set[dt.date]:
    """Every date with at least one logged session (any exercise) - for streaks."""
    return set(db.scalars(select(WorkoutSession.date).distinct()))


def all_sets(db: Session) -> List[Dict[str, Any]]:
    """Every logged set, oldest first - for CSV export."""
    rows = db.execute(
        select(WorkoutSession.date, Exercise.name, WorkoutSession.is_deload, SetEntry.set_number,
               SetEntry.weight, SetEntry.reps, SetEntry.rpe)
        .join(Exercise, WorkoutSession.exercise_id == Exercise.id)
        .join(SetEntry, SetEntry.session_id == WorkoutSession.id)
        .order_by(WorkoutSession.date, Exercise.name, WorkoutSession.id, SetEntry.set_number)
    )
    return [{"date": r[0].isoformat(), "exercise": r[1], "deload": r[2], "set": r[3],
             "weight_kg": r[4], "reps": r[5], "rpe": r[6]} for r in rows]


# ---------- preferences & settings (long-term memory) ----------

def save_preference(db: Session, key: str, value: str) -> Preference:
    key, value = normalize_name(key), value.strip()
    if not key or not value:
        raise ValueError("Preference key and value can't be empty.")
    pref = db.scalar(select(Preference).where(Preference.key == key))
    if pref is None:
        pref = Preference(key=key, value=value)
        db.add(pref)
    else:
        pref.value = value
    db.flush()
    return pref


def list_preferences(db: Session) -> List[Preference]:
    return list(db.scalars(select(Preference).order_by(Preference.key)))


def get_setting(db: Session, key: str) -> Optional[str]:
    row = db.get(Setting, key)
    return row.value if row else None


def set_setting(db: Session, key: str, value: str) -> None:
    row = db.get(Setting, key)
    if row is None:
        db.add(Setting(key=key, value=value))
    else:
        row.value = value
    db.flush()


def set_day_plan(db: Session, day: str, exercise_names: Sequence[str]) -> List[str]:
    """Replace the exercises planned for a weekday (mon..sun). Empty list clears it."""
    day = day.strip().lower()[:3]
    if day not in WEEKDAYS:
        raise ValueError(f"Unknown day '{day}' - use mon, tue, wed, thu, fri, sat or sun.")
    exercises = [_require_exercise(db, n) for n in exercise_names]
    for row in db.scalars(select(DayPlan).where(DayPlan.day == day)):
        db.delete(row)
    db.flush()
    for i, ex in enumerate(dict.fromkeys(exercises)):
        db.add(DayPlan(day=day, exercise_id=ex.id, position=i))
    db.flush()
    return [ex.name for ex in dict.fromkeys(exercises)]


def get_day_plan(db: Session) -> Dict[str, List[str]]:
    """{'mon': ['bench press', 'squat'], ...} - only days that have a plan."""
    plan: Dict[str, List[str]] = {}
    for row in db.scalars(select(DayPlan).order_by(DayPlan.day, DayPlan.position)):
        plan.setdefault(row.day, []).append(row.exercise.name)
    return plan


# ---------- meals ----------

def add_meal(db: Session, date: dt.date, text: str, protein_g: Optional[float], estimated: bool) -> Meal:
    text = text.strip()
    if not text:
        raise ValueError("Meal text can't be empty.")
    if protein_g is not None and protein_g < 0:
        raise ValueError("Protein can't be negative.")
    meal = Meal(date=date, text=text[:500], protein_g=protein_g, protein_estimated=estimated)
    db.add(meal)
    db.flush()
    return meal


def set_meal_protein(db: Session, meal_id: int, protein_g: float) -> Meal:
    """The user's own number replaces the estimate."""
    meal = db.get(Meal, meal_id)
    if meal is None:
        raise ValueError(f"No meal with id {meal_id}.")
    if protein_g < 0:
        raise ValueError("Protein can't be negative.")
    meal.protein_g, meal.protein_estimated = float(protein_g), False
    db.flush()
    return meal


def meals_between(db: Session, start: dt.date, end: dt.date) -> List[Meal]:
    return list(db.scalars(select(Meal).where(Meal.date >= start, Meal.date <= end).order_by(Meal.date, Meal.id)))


def all_meals(db: Session) -> List[Meal]:
    return list(db.scalars(select(Meal).order_by(Meal.date, Meal.id)))


# ---------- notifications ----------

def record_notification(db: Session, date: dt.date, kind: str) -> None:
    db.add(Notification(date=date, kind=kind))
    db.flush()


def notifications_on(db: Session, date: dt.date) -> List[str]:
    return list(db.scalars(select(Notification.kind).where(Notification.date == date).order_by(Notification.id)))

# ---------- connection check (run: python db.py) ----------

if __name__ == "__main__":
    from sqlalchemy import inspect

    eng = get_engine()
    print("Connected:", describe_engine(eng))
    print("Tables:", ", ".join(sorted(inspect(eng).get_table_names())))
