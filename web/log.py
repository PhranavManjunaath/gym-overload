"""📝 Log workout - same text format as Telegram, with a preview before saving."""
from __future__ import annotations

import datetime as dt

import streamlit as st

import formatting
import parser as workout_parser
import tools
from web import common


def _save(text: str, day: dt.date) -> None:
    """Button callback: runs once per click, before the rerun, so a double render can't save twice."""
    with common.session_factory()() as s:
        result = tools.log_workout(s, text, today=day)
        if result["status"] != "ok":
            s.rollback()
            st.session_state.log_error = result["message"]
            return
        s.commit()
        names = list(dict.fromkeys(e["exercise"] for e in result["logged"]))
        st.session_state.log_result = (result, [tools.recommend_next(s, n) for n in names])
    st.session_state.log_text = ""


st.title("📝 Log workout")
st.caption("Same format as Telegram. Nothing is saved until you press Save.")

if "log_result" in st.session_state:
    result, recs = st.session_state.pop("log_result")
    st.success("Saved!")
    common.text_block(formatting.format_logged(result))
    for rec in recs:
        common.text_block(formatting.format_recommendation(rec))
if "log_error" in st.session_state:
    st.error(st.session_state.pop("log_error"))

today = dt.date.today()
day = st.date_input("Date", value=today, max_value=today)
text = st.text_area("Workout", key="log_text", height=120,
                    placeholder="bench 60x10,10,9 @8\nsquat 100x5,5,5")
with st.expander("Format help"):
    common.text_block(workout_parser.HELP)

if text.strip():
    try:
        entries = workout_parser.parse_message(text, today=day)
    except workout_parser.ParseError as e:
        st.error(str(e))
    else:
        known = {e["exercise"] for e in common.exercises()}
        missing = sorted({e.exercise for e in entries} - known)

        st.subheader("Preview")
        for e in entries:
            sets = [{"weight_kg": s.weight, "reps": s.reps, "rpe": s.rpe} for s in e.sets]
            tag = " · deload" if e.is_deload else ""
            st.markdown(f"**{e.exercise}** · {e.date.isoformat()}{tag}")
            common.text_block(formatting.format_sets(sets))
        if missing:
            st.warning(f"Not set up yet: {', '.join(missing)}. Add them on the Exercises page "
                       "(sidebar) first.")
        st.button("Save", type="primary", disabled=bool(missing), on_click=_save, args=(text, day))
