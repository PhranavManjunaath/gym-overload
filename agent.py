"""
Agent - LangGraph loop: the LLM picks tools, Python does the work, the LLM explains.

    START -> agent --(tool calls)--> tools -> agent -> ...
                   +--(final text)--> verify --(all numbers grounded)--> END
                                            +--(made-up number)--> agent (one retry)
                                            +--(still made up)--> deterministic fallback -> END

verify enforces the golden rule: every number in the reply must appear in a tool
result or in something the user wrote. After the graph, a "Numbers used" block is
built in plain Python from this turn's tool results, so the evidence is always shown.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
from typing import Annotated, Any, Callable, Dict, List, Optional, Set

from dotenv import load_dotenv
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import InjectedState, ToolNode
from sqlalchemy.orm import Session, sessionmaker

import db as storage
import formatting
import tools

DEFAULT_MODEL = "openai/gpt-oss-120b"
MAX_HISTORY = 30          # messages sent to the LLM per call (older ones are dropped)
MAX_RETRIES = 1           # rewrites allowed when the reply has an ungrounded number
VERIFIER = "verifier"     # name on the correction message verify sends back to the LLM
EVIDENCE_TOOLS = ("log_workout", "recommend_next", "plan_first_session", "log_meal", "correct_meal_protein")

SYSTEM_PROMPT = """You are a strength coach inside a Telegram chat. Today is {today}.

WHAT YOU KNOW ABOUT THE USER (long-term memory, from the database):
{memory}

HARD RULES
1. Always call a tool for any number. Never calculate, estimate or invent any number
   (weights, reps, sets, e1RM, volume, protein, percentages, dates, streaks).
   Every number you write must be copied exactly from a tool result or the user's message.
   When giving a recommendation, quote the tool output numbers exactly.
   If a tool returns an error, say so plainly - never fill the gap with made-up data.
   If the exercise or the data is unclear, ask a short question instead of guessing.
2. To save a workout, call log_workout with the workout part of the user's message copied
   character for character (e.g. "bench 60x10,10,9 @8"). Never fix or change it.
   On parse_error, show the message and ask the user to resend.
3. After a workout is saved, call recommend_next for each logged exercise and give the next target.
4. For "what next" questions call recommend_next. Say the next weight and reps, the rule that
   fired, and the last session it was based on.
5. need_starting_weight -> ask the user for a starting weight. Never suggest one.
   When they give it, call plan_first_session.
6. Adding exercises: if the user names the equipment as barbell or dumbbell, call add_exercise
   immediately - the defaults already cover the weight jump, so do NOT ask for it. Only for other
   equipment (machine, cable, ...) ask for the smallest weight jump in kg. On unknown_exercise,
   ask only "barbell, dumbbell or other?". Pass only settings the user actually stated.
   If the user sent a workout for an exercise that wasn't set up, log it again after adding
   (call log_workout with the same text from their earlier message).
7. Which tool (exercise names are listed in your memory above - use them directly, don't call
   list_exercises just to look a name up):
   • past sessions / "what did I do" -> get_history
   • "am I stuck / plateau" -> check_plateau
   • trends over weeks, best set, "how am I progressing" -> progress_summary
   • change rep range, weight jump or sets -> update_exercise_settings
   • a lasting fact about the user (likes, dislikes, injuries, equipment) -> save_preference;
     their training goal -> set_goal
   • training days or reminder time -> set_schedule; exercises for a weekday -> set_day_plan
   • streak or consistency -> get_streak
   • a meal they ate -> log_meal (pass the meal text exactly); fixing a meal's protein ->
     correct_meal_protein; protein target -> set_protein_target; protein so far today -> protein_today
8. Protein numbers come only from the tools (a fixed food table, labelled "estimated"). If a meal
   can't be estimated, ask the user for the grams. Track against the user's own target only:
   never give calorie-restriction or diet advice.

STYLE: short, friendly, plain text - no markdown (no **bold**, *italics*, # headings or `code`).
Use bullets (•), never numbered lists, no tables, no JSON.
A "Numbers used" block is added under your reply automatically - no need to repeat every detail."""

_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")


# ---------- number grounding ----------

def extract_numbers(text: str) -> Set[float]:
    """'60x10, 62.5 kg on 2026-10-27' -> {60, 10, 62.5, 2026, 27}."""
    return {float(n) for n in _NUMBER_RE.findall(text or "")}


def ungrounded_numbers(reply: str, sources: List[str]) -> List[str]:
    """Numbers in `reply` that appear in none of `sources` (as written, e.g. ['65'])."""
    allowed: Set[float] = set()
    for s in sources:
        allowed |= extract_numbers(s)
    seen: List[str] = []
    for n in _NUMBER_RE.findall(reply or ""):
        if float(n) not in allowed and n not in seen:
            seen.append(n)
    return seen


def _text(m: BaseMessage) -> str:
    return m.content if isinstance(m.content, str) else json.dumps(m.content)


def _is_user(m: BaseMessage) -> bool:
    return isinstance(m, HumanMessage) and m.name != VERIFIER


# ---------- tools wired to the database ----------

def _recent_user_texts(state: Dict[str, Any], n: int = 2) -> List[str]:
    """The user's last `n` messages, newest first."""
    return [_text(m) for m in reversed(state["messages"]) if _is_user(m)][:n]


def _squash(s: str) -> str:
    return " ".join(s.lower().split())


def _already_logged(state: Dict[str, Any], text: str) -> bool:
    """Was this exact workout text saved successfully earlier in the conversation?"""
    msgs = state["messages"]
    ok_ids = {m.tool_call_id for m in msgs if isinstance(m, ToolMessage) and m.name == "log_workout"
              and '"status": "ok"' in _text(m)}
    return any(tc["name"] == "log_workout" and tc["id"] in ok_ids
               and _squash(tc["args"].get("text", "")) == _squash(text)
               for m in msgs if isinstance(m, AIMessage) for tc in m.tool_calls)


def build_tools(SessionLocal: sessionmaker[Session],
                today: Callable[[], dt.date] = dt.date.today) -> List[BaseTool]:
    """LangChain tools around tools.py. Each call = one DB transaction, result as JSON."""

    def run(fn: Callable[..., Dict[str, Any]], **kwargs: Any) -> str:
        with SessionLocal() as s:
            result = fn(s, **kwargs)
            if result.get("status") == "ok":
                s.commit()
            else:
                s.rollback()
        return json.dumps(result)

    def log_workout(text: str, state: Annotated[dict, InjectedState]) -> str:
        """Save a workout. `text` = the workout part of the user's latest (or previous) message,
        copied exactly, e.g. 'bench 60x10,10,9 @8'. Several exercises: one per line."""
        if not any(_squash(text) in _squash(t) for t in _recent_user_texts(state)):
            # The LLM may only cut chit-chat away - never retype numbers.
            return json.dumps({"status": "error", "message": "Nothing saved: text must be copied exactly "
                               "from the user's latest message."})
        if _already_logged(state, text):
            return json.dumps({"status": "error", "message": "Nothing saved: this workout was already saved."})
        return run(tools.log_workout, text=text, today=today())

    def recommend_next(exercise: str) -> str:
        """Next session's weight and reps for an exercise, with the rule and data it was based on."""
        return run(tools.recommend_next, exercise=exercise)

    def plan_first_session(exercise: str, starting_weight_kg: float) -> str:
        """First session for an exercise with no history. starting_weight_kg MUST be a weight the user stated."""
        return run(tools.plan_first_session, exercise=exercise, starting_weight_kg=starting_weight_kg)

    def add_exercise(name: str, equipment: str = "barbell", rep_min: Optional[int] = None,
                     rep_max: Optional[int] = None, increment_kg: Optional[float] = None,
                     target_sets: Optional[int] = None) -> str:
        """Set up a new exercise. Leave settings empty unless the user stated them
        (defaults: 6-10 reps, 3 sets, +2.5 kg barbell, +2 kg dumbbell; other equipment needs increment_kg)."""
        return run(tools.add_exercise, name=name, equipment=equipment, rep_min=rep_min, rep_max=rep_max,
                   increment_kg=increment_kg, target_sets=target_sets)

    def list_exercises() -> str:
        """All exercises the user has set up, with their settings."""
        return run(tools.list_exercises)

    def get_progress(exercise: str, last_n: Optional[int] = None) -> str:
        """Per-session chart data for an exercise: working weight, total reps, volume, best e1RM."""
        return run(tools.get_progress, exercise=exercise, last_n=last_n)

    def get_history(exercise: str, n: int = 5) -> str:
        """The last n logged sessions of an exercise with every set (weight, reps, RPE)."""
        return run(tools.get_history, exercise=exercise, n=n)

    def check_plateau(exercise: str) -> str:
        """Whether an exercise has plateaued (engine rule), with the sessions checked."""
        return run(tools.check_plateau, exercise=exercise)

    def progress_summary(exercise: str, weeks: int = 4) -> str:
        """Trend over the last `weeks` weeks: e1RM change, volume change, total volume, best set."""
        return run(tools.progress_summary, exercise=exercise, weeks=weeks, today=today())

    def update_exercise_settings(exercise: str, rep_min: Optional[int] = None, rep_max: Optional[int] = None,
                                 increment_kg: Optional[float] = None, target_sets: Optional[int] = None) -> str:
        """Change an exercise's rep range, weight jump (kg) or number of sets. Pass only what the user stated."""
        return run(tools.update_exercise_settings, exercise=exercise, rep_min=rep_min, rep_max=rep_max,
                   increment_kg=increment_kg, target_sets=target_sets)

    def save_preference(key: str, value: str) -> str:
        """Remember a lasting fact about the user, e.g. key='dislikes', value='lunges'."""
        return run(tools.save_preference, key=key, value=value)

    def set_goal(goal: str) -> str:
        """Save the user's training goal in their own words."""
        return run(tools.set_goal, goal=goal)

    def set_schedule(training_days: Optional[str] = None, workout_time: Optional[str] = None) -> str:
        """Set training days (e.g. 'mon,wed,fri') and/or the daily reminder time (24h 'HH:MM')."""
        return run(tools.set_schedule, training_days=training_days, workout_time=workout_time)

    def set_day_plan(day: str, exercises: List[str]) -> str:
        """Set which exercises are trained on a weekday (mon..sun) - used in that day's reminder."""
        return run(tools.set_day_plan, day=day, exercises=exercises)

    def get_streak() -> str:
        """Current and best streak of completed training days, and consistency over 4 weeks."""
        return run(tools.streak, today=today())

    def log_meal(text: str, state: Annotated[dict, InjectedState]) -> str:
        """Save a meal. `text` = the meal from the user's latest message, copied exactly
        (e.g. 'chicken 200g, 2 eggs'). Protein is estimated in Python from a food table."""
        if not any(_squash(text) in _squash(t) for t in _recent_user_texts(state)):
            return json.dumps({"status": "error", "message": "Nothing saved: meal text must be copied exactly "
                               "from the user's message."})
        return run(tools.log_meal, text=text, today=today())

    def correct_meal_protein(meal_id: int, protein_g: float) -> str:
        """Replace a meal's protein with the grams the user stated."""
        return run(tools.correct_meal_protein, meal_id=meal_id, protein_g=protein_g)

    def set_protein_target(grams: float) -> str:
        """Save the user's own daily protein target in grams (only a number the user stated)."""
        return run(tools.set_protein_target, grams=grams)

    def protein_today() -> str:
        """Today's meals, total protein so far and the user's target."""
        return run(tools.protein_day, day=today())

    return [StructuredTool.from_function(f) for f in
            (log_workout, recommend_next, plan_first_session, add_exercise, list_exercises, get_progress,
             get_history, check_plateau, progress_summary, update_exercise_settings, save_preference,
             set_goal, set_schedule, set_day_plan, get_streak, log_meal, correct_meal_protein,
             set_protein_target, protein_today)]


# ---------- graph ----------

class CoachState(MessagesState):
    turn_start: int     # index of this turn's user message in `messages`
    retries: int


def _trim(messages: List[BaseMessage], turn_start: int) -> List[BaseMessage]:
    """Last MAX_HISTORY messages, starting on a user message, never cutting into this turn."""
    start = max(0, len(messages) - MAX_HISTORY)
    while start < turn_start and not _is_user(messages[start]):
        start += 1
    return messages[min(start, turn_start):]


def _turn_tool_results(messages: List[BaseMessage], turn_start: int) -> List[tuple]:
    """(tool_name, result dict) for every tool call made this turn, in order."""
    out = []
    for m in messages[turn_start:]:
        if isinstance(m, ToolMessage):
            try:
                out.append((m.name, json.loads(_text(m))))
            except json.JSONDecodeError:
                pass
    return out


def fallback_reply(messages: List[BaseMessage], turn_start: int) -> str:
    results = _turn_tool_results(messages, turn_start)
    if not results:
        return "Sorry, I couldn't answer that reliably. Try /help for what I can do."
    return "\n\n".join(formatting.format_any(name, r) for name, r in results)


def build_graph(llm: BaseChatModel, tool_list: List[BaseTool],
                today: Callable[[], dt.date] = dt.date.today, checkpointer: Any = None,
                memory: Callable[[], str] = lambda: "nothing saved yet") -> Any:
    llm_with_tools = llm.bind_tools(tool_list)

    def agent(state: CoachState) -> Dict[str, Any]:
        system = SystemMessage(SYSTEM_PROMPT.format(today=today().isoformat(), memory=memory()))
        reply = llm_with_tools.invoke([system] + _trim(state["messages"], state["turn_start"]))
        return {"messages": [reply]}

    def after_agent(state: CoachState) -> str:
        last = state["messages"][-1]
        return "tools" if isinstance(last, AIMessage) and last.tool_calls else "verify"

    def verify(state: CoachState) -> Dict[str, Any]:
        msgs = state["messages"]
        final = msgs[-1]
        sources = [_text(m) for m in msgs if _is_user(m) or isinstance(m, ToolMessage)]
        sources += [today().isoformat(), memory()]          # saved goal/target/schedule may be quoted
        bad = ungrounded_numbers(_text(final), sources)
        if not bad:
            return {}
        if state["retries"] < MAX_RETRIES:
            return {"retries": state["retries"] + 1, "messages": [HumanMessage(
                name=VERIFIER,
                content=f"Your reply used numbers that are not in any tool result or user message: "
                        f"{', '.join(bad)}. Rewrite it using only numbers copied exactly from tool results "
                        f"(call a tool if you need one).")]}
        # Same id -> replaces the bad reply in the conversation history.
        return {"messages": [AIMessage(content=fallback_reply(msgs, state["turn_start"]), id=final.id)]}

    def after_verify(state: CoachState) -> str:
        last = state["messages"][-1]
        return "agent" if isinstance(last, HumanMessage) and last.name == VERIFIER else END

    g = StateGraph(CoachState)
    g.add_node("agent", agent)
    g.add_node("tools", ToolNode(tool_list))
    g.add_node("verify", verify)
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", after_agent, ["tools", "verify"])
    g.add_edge("tools", "agent")
    g.add_conditional_edges("verify", after_verify, ["agent", END])
    return g.compile(checkpointer=checkpointer if checkpointer is not None else InMemorySaver())


# ---------- public entry point ----------

class Coach:
    """One coach for the app; conversation memory is kept per Telegram chat id."""

    def __init__(self, llm: BaseChatModel, SessionLocal: sessionmaker[Session],
                 today: Callable[[], dt.date] = dt.date.today, checkpointer: Any = None) -> None:
        def memory() -> str:
            with SessionLocal() as s:
                return tools.memory_context(s)

        self.graph = build_graph(llm, build_tools(SessionLocal, today), today, checkpointer, memory)
        self.last_trace: Dict[str, Any] = {}

    def chat(self, chat_id: int | str, text: str) -> str:
        config = {"configurable": {"thread_id": str(chat_id)}, "recursion_limit": 25}
        before = len(self.graph.get_state(config).values.get("messages", []))
        state = self.graph.invoke({"messages": [HumanMessage(text)], "turn_start": before, "retries": 0}, config)
        msgs = state["messages"]
        reply = _text(msgs[-1]).strip()
        # For evaluation/debugging: which tools ran this turn and whether verify had to step in.
        self.last_trace = {
            "tools": [tc["name"] for m in msgs[before:] if isinstance(m, AIMessage) for tc in m.tool_calls],
            "tool_outputs": [_text(m) for m in msgs[before:] if isinstance(m, ToolMessage)],
            "retries": state.get("retries", 0),
            "reply": reply,
        }
        evidence = [formatting.format_any(name, r) for name, r in _turn_tool_results(msgs, before)
                    if name in EVIDENCE_TOOLS and r.get("status") == "ok"]
        if evidence and reply != fallback_reply(msgs, before):   # fallback already is the numbers
            reply += "\n\n📊 Numbers used\n" + "\n\n".join(evidence)
        return reply


def build_llm() -> BaseChatModel:
    from langchain_groq import ChatGroq

    load_dotenv(storage.PROJECT_DIR / ".env")
    if not os.getenv("GROQ_API_KEY"):
        raise RuntimeError("GROQ_API_KEY is missing from .env")
    return ChatGroq(model=os.getenv("GROQ_MODEL", DEFAULT_MODEL), temperature=0, max_retries=2)


def create_coach(SessionLocal: Optional[sessionmaker[Session]] = None) -> Coach:
    """The real coach: Groq LLM + the database from DATABASE_URL."""
    if SessionLocal is None:
        SessionLocal = storage.make_session_factory(storage.get_engine())
    return Coach(build_llm(), SessionLocal)
