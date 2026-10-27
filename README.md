# Gym Overload

An agentic AI gym coach that applies progressive overload to **your real workout
data**, and sends workout/diet reminders to keep you consistent.

## Key idea

The LLM never does math. Every weight, rep and e1RM comes from plain, tested
Python (`progression_engine.py`). The agent calls it as a tool and explains the
result, always showing the numbers and the rule that produced it.

## Stack

Python 3.11 · SQLite (SQLAlchemy) · python-telegram-bot · LangGraph · Groq ·
APScheduler · Streamlit · pytest

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env   # then fill in your keys
pytest
```

## Status

Project skeleton only. See `CLAUDE.md` for project rules.
