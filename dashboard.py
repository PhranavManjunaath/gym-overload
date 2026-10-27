"""
Dashboard - progress charts in the browser. Run: streamlit run dashboard.py

Read-only view of the same database the bot writes to. Every number shown
comes from tools.py / progression_engine.py - nothing is calculated here.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st
from sqlalchemy.orm import Session, sessionmaker

import db as storage
import formatting
import tools


@st.cache_resource
def session_factory(url: str) -> sessionmaker[Session]:
    return storage.make_session_factory(storage.get_engine(url))


st.set_page_config(page_title="Gym Overload", page_icon="🏋️", layout="wide")
st.title("🏋️ Gym Overload")
st.caption("Progressive overload from your real workouts. All numbers come from tested Python, not the AI.")

SessionLocal = session_factory(storage.database_url())
with SessionLocal() as s:
    exercises = tools.list_exercises(s)["exercises"]

if not exercises:
    st.info("No exercises yet. Add one in Telegram, e.g. 'add bench press, barbell'.")
    st.stop()

names = [e["exercise"] for e in exercises]
choice = st.selectbox("Exercise", names)
settings = next(e for e in exercises if e["exercise"] == choice)["settings"]

with SessionLocal() as s:
    progress = tools.get_progress(s, choice)
    rec = tools.recommend_next(s, choice)

sessions = progress["sessions"]
st.caption(f"{settings['rep_min']}-{settings['rep_max']} reps · {settings['target_sets']} sets · "
           f"+{formatting.kg(settings['increment_kg'])} per jump")

# ----- next session -----
st.subheader("Next session")
if rec["status"] == "ok":
    st.markdown(f"### {formatting.format_targets(rec['next'])}")
    st.write(f"**Rule:** `{rec['rule']}` - {rec['rule_explained']}")
    with st.expander("Sessions this is based on"):
        for sess in rec["based_on"]["recent_sessions"]:
            st.write(f"• {formatting.format_session(sess)} - total reps {sess['total_reps']}")
else:
    st.info(rec["message"])

if not sessions:
    st.stop()

# ----- latest numbers -----
last = sessions[-1]
c1, c2, c3, c4 = st.columns(4)
c1.metric("Working weight", formatting.kg(last["working_weight_kg"]))
c2.metric("Total reps", last["total_reps"])
c3.metric("Volume", formatting.kg(last["volume_kg"]))
c4.metric("Est. 1RM (Epley)", formatting.kg(last["best_e1rm_kg"]))
st.caption(f"Latest session: {last['date']}" + (" (deload)" if last["deload"] else ""))

# ----- charts -----
df = pd.DataFrame(sessions)
df["date"] = pd.to_datetime(df["date"])
df = df.set_index("date")

left, right = st.columns(2)
with left:
    st.subheader("Working weight (kg)")
    st.line_chart(df[["working_weight_kg"]], y_label="kg")
with right:
    st.subheader("Estimated 1RM (kg)")
    st.line_chart(df[["best_e1rm_kg"]], y_label="kg")
    st.caption("e1RM is for tracking progress only - it never picks your next weight.")

st.subheader("Volume per session (kg)")
st.bar_chart(df[["volume_kg"]], y_label="kg")

st.subheader("History")
table = pd.DataFrame(sessions)[["date", "working_weight_kg", "total_reps", "volume_kg", "best_e1rm_kg", "deload"]]
table.columns = ["Date", "Weight (kg)", "Total reps", "Volume (kg)", "e1RM (kg)", "Deload"]
st.dataframe(table.iloc[::-1], hide_index=True, use_container_width=True)
