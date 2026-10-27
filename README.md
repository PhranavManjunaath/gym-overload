# Gym Overload

An agentic AI gym coach on Telegram that applies **progressive overload to your
real workout data**, plus workout and meal reminders to keep you consistent.

## Key idea: the AI never does math

LLMs are bad at arithmetic, and in a progression app one wrong number ruins every
future recommendation. So:

1. **All math is plain, tested Python** (`progression_engine.py`, double progression).
2. **The agent can only call tools** (`tools.py`). Every number it sees comes from the
   engine or the database, together with the rule that fired and the sessions behind it.
3. **A verify step checks every reply.** If the LLM writes a number that isn't in a tool
   result or your message, the reply is rejected and rewritten. If it happens again,
   a plain-Python answer is sent instead.
4. **A "📊 Numbers used" block** is added under every recommendation by Python, so you
   can always check the evidence.

```
You: bench 60x10,10,10 @8
Coach: Great session! You hit 10 reps on every set, so next time go 62.5 kg for 6 reps.

📊 Numbers used
Saved bench 2026-10-27: 60 kg × 10, 10, 10 (RPE 8, 8, 8)

Next bench: 62.5 kg × 6, 6, 6
Rule: increase_weight - All working sets reached 10 reps (RPE <= 9 where logged) -> add 2.5 kg and restart at 6 reps.
Based on: 2026-10-27: 60 kg × 10, 10, 10 (RPE 8, 8, 8)
```

## Ways to use it (separate front ends, same data)

| | Website (`frontend/` + `api.py`) | Telegram bot (`bot.py`) | Streamlit app (`dashboard.py`) |
|---|---|---|---|
| Log workouts | Live preview → Save, set-by-set table | send `bench 60x10,10,9` | Preview before saving |
| Next targets | Recommendation cards with an Evidence panel | `/next bench` or ask | "Why?" box per lift |
| Progress | Weight / e1RM / volume charts, history | `/progress bench` | Charts + history |
| Exercises | Search + add form | "add squat, barbell" | Form |
| AI coach | Chat with a "Numbers used" panel | every text message | Chat page |
| Streak & consistency | Dashboard stats + "This week" card | `/streak`, in reminders | Progress page |
| Protein tracking | Nutrition page (add, correct, target) | `/meal`, `/fixmeal`, `/setprotein`, `/protein` | - |
| Weekly report | "This week" card | Sunday 19:00 + `/report` | - |
| Schedule | Settings (days, time, goal) | `/schedule`, `/plan`, `/goal` | - |
| Export CSV | Settings → Your data | `/export` | Progress page |
| Undo / fresh start | - | `/resetday` (one day), `/reset` (everything) - both ask first | - |
| Reminders | Shown in Settings | ✅ sends them (max 2/day) | - |

None of the front ends import each other; they share the database, tools, engine and
agent, so the numbers always match. The website is the main UI; the Streamlit app is kept
as a simpler alternative.

## Architecture

```
frontend/ (Next.js) ─HTTP─▶ api.py (FastAPI, no logic) ─▶ tools.py / agent.py
dashboard.py + web/ (Streamlit app) ─▶ tools.py / agent.py   (same core, no bot)
Telegram ─▶ bot.py ─▶ agent.py (LangGraph: agent ⇄ tools ─▶ verify) ─▶ Groq LLM
                │            │
                │            └─▶ tools.py ─▶ progression_engine.py (all math)
                │                     └────▶ db.py ─▶ Supabase Postgres (or SQLite)
                ├─▶ /next /progress: tools.py directly (no LLM)
                └─▶ scheduler.py (APScheduler, 1-min check, max 2 msgs/day):
                      workout reminder, 9 pm nudge, Sunday report, meal reminders
parser.py: "bench 60x10,10,9 @8" ─▶ exact sets (regex, no LLM)
analytics.py: streaks, consistency, e1RM milestones, trend summaries (plain Python)
nutrition.py: "chicken 200g, 2 eggs" ─▶ protein from a fixed food table (no LLM, labelled estimated)
reports.py: weekly report numbers + CSV export (LLM summary only if every number checks out)
formatting.py: tool results ─▶ plain text (no LLM)
```

## Agent (LangGraph + Groq)

19 tools, each a thin wrapper around tested Python: `log_workout`, `get_history`, `recommend_next`,
`check_plateau`, `progress_summary`, `update_exercise_settings`, `save_preference`, `set_goal`,
`set_schedule`, `set_day_plan`, `get_streak`, `log_meal`, `correct_meal_protein`, `set_protein_target`,
`protein_today`, `add_exercise`, `list_exercises`, `get_progress`, `plan_first_session`.

**Long-term memory:** goal, exercises, schedule, per-day plan, protein target and saved preferences
are loaded from the database into the prompt every turn.

**Evaluation** (`python -m tests.eval_agent`, real Groq, throwaway DB): 20 messages with the expected
tool, reporting tool-selection accuracy and a "no hallucinated numbers" check (every number in the
reply must appear in a tool output, the message or the saved memory).

## Progression method (double progression)

| Last session | Next session |
|---|---|
| All sets hit `rep_max` (RPE ≤ 9 if logged) | + increment, back to `rep_min` |
| All sets ≥ `rep_min` | Same weight, +1 rep on sets below `rep_max` |
| Any set < `rep_min` | Repeat the weight |
| Two failed sessions in a row at the same weight | 95%, rounded down to the increment |
| 3 sessions at the same weight, no gain in total reps | One deload at 90%, then resume |

Defaults: 6-10 reps, 3 sets, +2.5 kg barbell, +2 kg dumbbell. e1RM (Epley) is for charts only.

## Stack

Python 3.11 · FastAPI · LangGraph · Groq (`openai/gpt-oss-120b`) · python-telegram-bot ·
SQLAlchemy · Supabase Postgres · APScheduler · Streamlit · pytest ·
Next.js 16 · TypeScript · Tailwind CSS 4 · Lucide · Recharts

## Setup

```bash
py -3.11 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env      # fill in your keys - see comments in the file
python db.py                # checks the database connection, creates tables
pytest                      # no API keys needed - the LLM is faked in tests
```

## Run

```bash
# Website (two terminals)
uvicorn api:create_app --factory --host 127.0.0.1 --port 8000
cd frontend && npm install && npm run dev      # → http://localhost:3000

python bot.py                 # Telegram bot + reminders (separate)
streamlit run dashboard.py    # Streamlit app → http://localhost:8501 (optional)
```

Everything listens on this computer only. Set `WEB_PASSWORD` in `.env` to require a
password (a single shared password - this is a personal app, not multi-user yet).

## Telegram usage

- Log: `bench 60x10,10,9`, `bench 60x10,10,9 @8`, `squat 100x5,5,5 deload yesterday`
- Ask: "what's next for bench?", "add squat, barbell", "how's my deadlift going?"
- Commands: `/next <exercise>`, `/progress <exercise>`, `/exercises`, `/reminders`, `/help`

## Tests

Every module has tests in `tests/`: engine rules, parser formats and bad input, DB storage,
tools (every rule returns its evidence), the agent graph (scripted fake LLM, including the
made-up-number rewrite and fallback), reminders, bot replies and chat lock, and every app page
(Streamlit `AppTest`: preview-before-save, never guessing a starting weight, password gate, and a
check that the app never imports the bot), and every API endpoint (preview never saves,
future dates rejected, password required, coach evidence split, no fake "save" for reminders).
The website is checked with `tsc`, ESLint and a production build.
