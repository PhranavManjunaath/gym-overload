"""💬 AI coach - the same agent as Telegram, in its own conversation."""
from __future__ import annotations

import uuid

import streamlit as st

from web import common

st.title("💬 AI coach")
st.caption("Log or ask in your own words. Every number is checked against your data, "
           "and the numbers used are shown under each answer.")

st.session_state.setdefault("chat_id", f"web-{uuid.uuid4()}")
st.session_state.setdefault("chat", [])

for role, text in st.session_state.chat:
    with st.chat_message(role):
        st.markdown(common.as_markdown(text))

prompt = st.chat_input("e.g. bench 60x10,10,9  ·  what's next for squat?")
if prompt:
    st.session_state.chat.append(("user", prompt))
    with st.chat_message("user"):
        st.markdown(common.as_markdown(prompt))
    with st.chat_message("assistant"), st.spinner("Thinking..."):
        try:
            reply = common.coach().chat(st.session_state.chat_id, prompt)
        except RuntimeError as e:                 # e.g. GROQ_API_KEY missing
            reply = f"The AI coach isn't set up: {e}. The other pages still work."
        except Exception:
            reply = "The AI coach is unavailable right now. Nothing was lost - the other pages still work."
        st.markdown(common.as_markdown(reply))
    st.session_state.chat.append(("assistant", reply))
