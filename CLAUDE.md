# Gym Overload — Project Rules

Agentic AI gym coach: progressive overload from the user's real workout data,
plus workout/diet reminders for consistency. Portfolio project.

## GOLDEN RULE — ACCURACY

- The LLM must NEVER calculate weights, reps, e1RM, volume or any number.
  All math lives in plain Python in `progression_engine.py`. The agent calls it
  as a tool and only explains the result in words.
- Do not change the formulas or rules in `progression_engine.py` unless the user
  asks. If you extend it, add tests and keep all existing tests passing.
- Every recommendation shown to the user must include the numbers it was based
  on (last session's sets, the rule that fired), so they can check it.
- If there's no history for an exercise, ask the user for a starting weight.
  Never guess.

## PROGRESSION METHOD (double progression — implemented in progression_engine.py)

- Per exercise: `rep_min`, `rep_max`, `increment` (kg), `target_sets`.
  Defaults: 6–10 reps, 2.5 kg barbell, 2 kg dumbbell, 3 sets.
- All working sets hit `rep_max` (and RPE <= 9 if logged) -> +increment, reset to `rep_min`.
- All sets >= `rep_min` -> same weight, +1 rep on sets below `rep_max`.
- Any set < `rep_min` -> repeat weight. Two failed sessions in a row at the same
  weight -> drop to 95%, rounded DOWN to the increment.
- 3 sessions in a row at the same weight with no gain in total reps -> plateau ->
  one deload session at 90% (rounded down), then resume.
- e1RM uses Epley: `w * (1 + reps/30)`; 1 rep = weight. Used for progress charts
  only, not for choosing the next weight.

## TECH STACK

- Python 3.11, SQLAlchemy, python-telegram-bot, LangGraph,
  LLM through Groq API (env var `GROQ_API_KEY`), APScheduler, Streamlit, pytest.
- Database: Supabase (PostgreSQL, psycopg driver) for real data, set via
  `DATABASE_URL` in `.env`. SQLite (`sqlite:///data/gym.db`) still works as a
  local fallback. Tests always use throwaway local SQLite files — never the real DB.
- Never print or log the database URL (it contains the password); use
  `db.describe_engine()` instead.
- Secrets only in a `.env` file (`.env` is in `.gitignore`). `.env.example` lists
  the required variables with placeholder values.

## CODE STYLE

- Small modules: `db.py`, `parser.py`, `tools.py`, `agent.py`, `bot.py`,
  `scheduler.py`, `dashboard.py`. Type hints everywhere. Tests in `tests/`.
- Run `pytest` after every change and show the result.
- At the end of each task, explain what was built in simple words so the user
  can explain it in interviews.
