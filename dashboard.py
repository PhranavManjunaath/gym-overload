"""
Gym Overload app - run: streamlit run dashboard.py

Separate from the Telegram bot (never imports bot.py); both share the same
database, tools and progression engine. Pages live in web/.
"""
import streamlit as st

from web import common

st.set_page_config(page_title="Gym Overload", page_icon="🏋️", layout="wide")
common.require_login()

st.navigation([
    st.Page("web/log.py", title="Log workout", icon="📝", default=True),
    st.Page("web/next.py", title="Next session", icon="🎯"),
    st.Page("web/progress.py", title="Progress", icon="📈"),
    st.Page("web/exercises.py", title="Exercises", icon="🏋️"),
    st.Page("web/coach.py", title="AI coach", icon="💬"),
]).run()
