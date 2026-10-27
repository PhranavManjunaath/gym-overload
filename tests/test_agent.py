"""Tests for agent.py with a scripted fake LLM - no network, no API key."""
import datetime as dt
from pathlib import Path
from typing import Any, Iterator, List

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from sqlalchemy.orm import Session, sessionmaker

import agent
import db as storage
import tools

TODAY = dt.date(2026, 10, 27)


class ScriptedLLM(BaseChatModel):
    """Returns the scripted AIMessages in order and records what it was sent."""
    script: List[AIMessage]
    seen: List[List[BaseMessage]] = []

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ScriptedLLM":
        return self

    def _generate(self, messages: List[BaseMessage], stop: Any = None, run_manager: Any = None,
                  **kwargs: Any) -> ChatResult:
        self.seen.append(list(messages))
        return ChatResult(generations=[ChatGeneration(message=self.script.pop(0))])


def call(tool: str, i: int = 0, **args: Any) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": tool, "args": args, "id": f"call_{tool}_{i}"}])


@pytest.fixture
def SessionLocal(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    engine = storage.get_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    factory = storage.make_session_factory(engine)
    with factory.begin() as s:
        tools.add_exercise(s, "bench")
    yield factory
    engine.dispose()


def coach(SessionLocal: sessionmaker[Session], script: List[AIMessage]) -> tuple:
    llm = ScriptedLLM(script=script, seen=[])
    return agent.Coach(llm, SessionLocal, today=lambda: TODAY), llm


def _history(SessionLocal: sessionmaker[Session], name: str = "bench") -> list:
    with SessionLocal() as s:
        return storage.get_history(s, name)


# ---------- number grounding helpers ----------

def test_extract_numbers() -> None:
    assert agent.extract_numbers("60x10, 62.5 kg on 2026-10-27") == {60, 10, 62.5, 2026, 27}


def test_ungrounded_numbers() -> None:
    sources = ['{"weight_kg": 62.5, "target_reps": [6, 6, 6]}', "bench 60x10,10,10"]
    assert agent.ungrounded_numbers("Go 62.5 kg for 6 reps (you did 60x10)", sources) == []
    assert agent.ungrounded_numbers("Go 65 kg for 6 reps, or 65.0", sources) == ["65", "65.0"]
    assert agent.ungrounded_numbers("62.50 kg", sources) == []          # same value, different spelling


# ---------- full turns ----------

def test_log_then_recommend_shows_numbers_used(SessionLocal: sessionmaker[Session]) -> None:
    c, llm = coach(SessionLocal, [
        call("log_workout", text="bench 60x10,10,10"),
        call("recommend_next", exercise="bench"),
        AIMessage("Nice work! Next time go 62.5 kg for 6 reps on each set."),
    ])
    reply = c.chat(1, "did bench 60x10,10,10 today")
    assert reply.startswith("Nice work! Next time go 62.5 kg")
    assert "📊 Numbers used" in reply
    assert "Saved bench 2026-10-27: 60 kg × 10, 10, 10" in reply
    assert "Next bench: 62.5 kg × 6, 6, 6" in reply
    assert "Rule: increase_weight" in reply
    assert len(_history(SessionLocal)) == 1
    assert "Today is 2026-10-27" in llm.seen[0][0].content       # system prompt


def test_log_workout_rejects_retyped_numbers(SessionLocal: sessionmaker[Session]) -> None:
    c, _ = coach(SessionLocal, [
        call("log_workout", text="bench 65x10,10,10"),             # LLM "fixed" the user's 60
        AIMessage("Sorry, please resend your workout."),
    ])
    reply = c.chat(1, "bench 60x10,10,10")
    assert _history(SessionLocal) == []
    assert "Numbers used" not in reply


def test_made_up_number_triggers_rewrite(SessionLocal: sessionmaker[Session]) -> None:
    with SessionLocal.begin() as s:
        tools.log_workout(s, "bench 60x10,10,10", today=TODAY)
    c, llm = coach(SessionLocal, [
        call("recommend_next", exercise="bench"),
        AIMessage("Go for 65 kg next time!"),                       # 65 is invented
        AIMessage("Go for 62.5 kg next time!"),
    ])
    reply = c.chat(1, "what's next for bench?")
    assert reply.startswith("Go for 62.5 kg next time!")
    correction = llm.seen[-1][-1]
    assert isinstance(correction, HumanMessage) and correction.name == agent.VERIFIER
    assert "65" in correction.content


def test_still_made_up_falls_back_to_plain_numbers(SessionLocal: sessionmaker[Session]) -> None:
    with SessionLocal.begin() as s:
        tools.log_workout(s, "bench 60x10,10,10", today=TODAY)
    c, _ = coach(SessionLocal, [
        call("recommend_next", exercise="bench"),
        AIMessage("Go for 65 kg!"),
        AIMessage("Okay, 67.5 kg then!"),
    ])
    reply = c.chat(1, "what's next for bench?")
    assert "65" not in reply and "67.5" not in reply
    assert reply.startswith("Next bench: 62.5 kg × 6, 6, 6")
    assert reply.count("Next bench") == 1                          # no duplicate evidence block


def test_numbers_from_user_message_are_allowed(SessionLocal: sessionmaker[Session]) -> None:
    c, _ = coach(SessionLocal, [AIMessage("A 100 kg bench is a great goal!")])
    assert c.chat(1, "I want to bench 100 kg one day") == "A 100 kg bench is a great goal!"


def test_no_history_asks_for_starting_weight(SessionLocal: sessionmaker[Session]) -> None:
    c, _ = coach(SessionLocal, [
        call("recommend_next", exercise="bench"),
        AIMessage("You have no bench history yet - what weight do you want to start with?"),
        call("plan_first_session", 1, exercise="bench", starting_weight_kg=40),
        AIMessage("Start with 40 kg for 6 reps on each set."),
    ])
    first = c.chat(1, "what should I bench?")
    assert "Numbers used" not in first
    second = c.chat(1, "40 kg")
    assert "Next bench: 40 kg × 6, 6, 6" in second and "starting weight you gave" in second


def test_unknown_exercise_then_add(SessionLocal: sessionmaker[Session]) -> None:
    c, _ = coach(SessionLocal, [
        call("log_workout", text="squat 100x5,5,5"),
        AIMessage("I don't know squat yet - barbell or dumbbell?"),
        call("add_exercise", 1, name="squat", equipment="barbell"),
        AIMessage("Added squat. Send the workout again to log it."),
    ])
    c.chat(1, "squat 100x5,5,5")
    assert _history(SessionLocal, "bench") == []
    c.chat(1, "barbell")
    with SessionLocal() as s:
        assert storage.get_exercise(s, "squat") is not None


def test_relog_previous_message_after_adding_exercise(SessionLocal: sessionmaker[Session]) -> None:
    c, _ = coach(SessionLocal, [
        call("log_workout", text="squat 100x5,5,5"),
        AIMessage("Barbell, dumbbell or other?"),
        call("add_exercise", 1, name="squat", equipment="barbell"),
        call("log_workout", 2, text="squat 100x5,5,5"),            # from the previous message
        AIMessage("Added squat and saved your workout."),
    ])
    c.chat(1, "squat 100x5,5,5")
    reply = c.chat(1, "barbell")
    assert len(_history(SessionLocal, "squat")) == 1
    assert "Saved squat 2026-10-27: 100 kg × 5, 5, 5" in reply


def test_same_workout_cannot_be_saved_twice(SessionLocal: sessionmaker[Session]) -> None:
    c, _ = coach(SessionLocal, [
        call("log_workout", text="bench 60x10,10,10"),
        AIMessage("Saved!"),
        call("log_workout", 1, text="bench 60x10,10,10"),          # LLM tries again next turn
        AIMessage("Thanks!"),
    ])
    c.chat(1, "bench 60x10,10,10")
    c.chat(1, "thanks")
    assert len(_history(SessionLocal)) == 1


def test_memory_is_per_chat(SessionLocal: sessionmaker[Session]) -> None:
    c, llm = coach(SessionLocal, [AIMessage("hi A"), AIMessage("hi B"), AIMessage("hi A again")])
    c.chat("A", "hello")
    c.chat("B", "hello")
    c.chat("A", "hello again")
    user_msgs = lambda msgs: [m.content for m in msgs if isinstance(m, HumanMessage)]
    assert user_msgs(llm.seen[1]) == ["hello"]                        # chat B saw only its own message
    assert user_msgs(llm.seen[2]) == ["hello", "hello again"]          # chat A remembers


def test_history_is_trimmed() -> None:
    msgs: List[BaseMessage] = []
    for i in range(40):
        msgs += [HumanMessage(f"q{i}"), AIMessage(f"a{i}")]
    trimmed = agent._trim(msgs, turn_start=78)
    assert len(trimmed) <= agent.MAX_HISTORY and isinstance(trimmed[0], HumanMessage)
    assert trimmed[-2].content == "q39"
