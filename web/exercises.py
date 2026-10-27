"""🏋️ Exercises - your lifts and their progression settings."""
from __future__ import annotations

import pandas as pd
import streamlit as st

import db as storage
import progression_engine as pe
import tools
from web import common

DEFAULTS = pe.ExerciseConfig("_")
EQUIPMENT = ["barbell", "dumbbell", "machine", "cable", "other"]
DEFAULT_JUMPS = ", ".join(f"{k} +{v:g} kg" for k, v in storage.DEFAULT_INCREMENTS.items())

st.title("🏋️ Exercises")
if "exercise_added" in st.session_state:
    st.success(f"Added {st.session_state.pop('exercise_added')}.")

exercises = common.exercises()
if exercises:
    st.dataframe(pd.DataFrame([{
        "Exercise": e["exercise"], "Equipment": e["equipment"],
        "Reps": f"{e['settings']['rep_min']}-{e['settings']['rep_max']}",
        "Sets": e["settings"]["target_sets"], "Jump (kg)": e["settings"]["increment_kg"],
    } for e in exercises]), hide_index=True, use_container_width=True)
else:
    st.info("No exercises yet - add your first one below.")

st.subheader("Add exercise")
with st.form("add_exercise", clear_on_submit=True):
    name = st.text_input("Name", placeholder="bench press")
    equipment = st.selectbox("Equipment", EQUIPMENT)
    c1, c2, c3 = st.columns(3)
    rep_min = c1.number_input("Min reps", min_value=1, value=DEFAULTS.rep_min, step=1)
    rep_max = c2.number_input("Max reps", min_value=1, value=DEFAULTS.rep_max, step=1)
    target_sets = c3.number_input("Sets", min_value=1, value=DEFAULTS.target_sets, step=1)
    increment = st.number_input("Weight jump (kg)", min_value=0.0, value=None, step=0.5,
                                help=f"Leave empty for the default ({DEFAULT_JUMPS}). "
                                     "Required for other equipment.")
    submitted = st.form_submit_button("Add", type="primary")

if submitted:
    with common.session_factory()() as s:
        r = tools.add_exercise(s, name, equipment, int(rep_min), int(rep_max), increment or None, int(target_sets))
        if r["status"] == "ok":
            s.commit()
    if r["status"] == "ok":
        st.session_state.exercise_added = r["exercise"]
        st.rerun()
    st.error(r["message"])
