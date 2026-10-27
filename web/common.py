"""
Shared helpers for the app pages (Streamlit).

The app is separate from the Telegram bot: it never imports bot.py. Both use the
same database, tools and progression engine, so the numbers always match.
"""
from __future__ import annotations

import hmac
import os
from typing import Any, Dict, List

import streamlit as st
from sqlalchemy.orm import Session, sessionmaker

import agent
import db as storage
import tools


@st.cache_resource
def _factory(url: str) -> sessionmaker[Session]:
    return storage.make_session_factory(storage.get_engine(url))


def session_factory() -> sessionmaker[Session]:
    """One connection pool per database URL, shared across reruns."""
    return _factory(storage.database_url())


@st.cache_resource
def _coach(url: str) -> agent.Coach:
    return agent.create_coach(_factory(url))


def coach() -> agent.Coach:
    return _coach(storage.database_url())


def exercises() -> List[Dict[str, Any]]:
    with session_factory()() as s:
        return tools.list_exercises(s)["exercises"]


def require_login() -> None:
    """If WEB_PASSWORD is set in .env, ask for it once per browser session."""
    storage.database_url()                       # loads .env
    password = os.getenv("WEB_PASSWORD", "")
    if not password or st.session_state.get("authed"):
        return
    st.title("🏋️ Gym Overload")
    with st.form("login"):
        typed = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Log in")
    if submitted:
        if hmac.compare_digest(typed.encode(), password.encode()):
            st.session_state.authed = True
            st.rerun()
        st.error("Wrong password.")
    st.stop()


def text_block(text: str) -> None:
    """Show engine output exactly as formatted (monospace, line breaks kept)."""
    st.code(text, language=None)


def as_markdown(text: str) -> str:
    """Keep single line breaks when rendering chat text as markdown."""
    return text.replace("\n", "  \n")
