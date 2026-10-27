"""Tests for dashboard.py using Streamlit's AppTest, on a throwaway SQLite database."""
import datetime as dt
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import db as storage
import tools

APP = str(Path(__file__).resolve().parent.parent / "dashboard.py")
TODAY = dt.date(2026, 10, 27)


@pytest.fixture
def db_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    url = f"sqlite:///{(tmp_path / 'dash.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)    # beats .env, so the real database is never touched
    return url


def _run() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    return at


def test_empty_database_shows_hint(db_url: str) -> None:
    storage.get_engine(db_url).dispose()
    at = _run()
    assert "No exercises yet" in at.info[0].value


def test_shows_next_session_metrics_and_history(db_url: str) -> None:
    engine = storage.get_engine(db_url)
    with storage.make_session_factory(engine).begin() as s:
        tools.add_exercise(s, "bench")
        tools.add_exercise(s, "squat")
        tools.log_workout(s, "bench 60x10,9,8 2026-10-20", today=TODAY)
        tools.log_workout(s, "bench 60x10,10,10 2026-10-23", today=TODAY)
    engine.dispose()

    at = _run()
    assert at.selectbox[0].options == ["bench", "squat"]
    assert any("62.5 kg × 6, 6, 6" in m.value for m in at.markdown)
    assert [m.value for m in at.metric] == ["60 kg", "30", "1800 kg", "80 kg"]
    assert len(at.dataframe[0].value) == 2

    at.selectbox[0].select("squat").run()
    assert not at.exception
    assert "starting weight" in at.info[0].value
