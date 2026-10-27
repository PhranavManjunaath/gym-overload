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
| Reminders | Read-only Settings page | ✅ sends them (APScheduler) | - |

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
                └─▶ scheduler.py (APScheduler): workout, missed-workout and meal reminders
parser.py: "bench 60x10,10,9 @8" ─▶ exact sets (regex, no LLM)
formatting.py: tool results ─▶ plain text (no LLM)
```

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
