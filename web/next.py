"""🎯 Next session - the engine's target for every exercise, with the evidence behind it."""
from __future__ import annotations

import streamlit as st

import formatting
import tools
from web import common

st.title("🎯 Next session")
st.caption("Picked by the progression engine from your logged sets - open \"Why?\" to check the numbers.")

exercises = common.exercises()
if not exercises:
    st.info("No exercises yet. Add one on the Exercises page.")
    st.stop()

with common.session_factory()() as s:
    recs = [(e, tools.recommend_next(s, e["exercise"])) for e in exercises]

for e, r in recs:
    name = e["exercise"]
    with st.container(border=True):
        st.subheader(name)
        if r["status"] == "ok":
            st.markdown(f"### {formatting.format_targets(r['next'])}")
            st.caption(f"Rule: {r['rule']}")
            with st.expander("Why?"):
                common.text_block(formatting.format_recommendation(r))
        elif r["status"] == "need_starting_weight":
            st.info("No history yet. Choose your starting weight - the coach never guesses one.")
            weight = st.number_input("Starting weight (kg)", min_value=0.0, value=None,
                                     step=float(e["settings"]["increment_kg"]), key=f"start_{name}")
            if weight:
                with common.session_factory()() as s:
                    common.text_block(formatting.format_recommendation(
                        tools.plan_first_session(s, name, weight)))
        else:
            st.warning(r.get("message", r["status"]))
