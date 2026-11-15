"""Streamlit UI for Version 1.  Run with:  streamlit run v1/app.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st  # noqa: E402

from common import llm_client  # noqa: E402
from v1.game import INTRO, GameSession  # noqa: E402

st.set_page_config(page_title="AI Escape Room - V1", page_icon="🔐")
st.title("🔐 AI Escape Room — Version 1")
st.caption("The LLM is the Game Master *and* the rule keeper (no Python validation).")

with st.sidebar:
    st.header("How to play")
    st.markdown(
        "- Type what you want to do in plain English.\n"
        "- Examples: *examine the bookshelf*, *take the key*, "
        "*try 1234 on the drawer*.\n"
        "- Find clues, collect items and open the door to escape."
    )
    if st.button("🔄 Restart game", use_container_width=True):
        st.session_state.session = GameSession()
        st.session_state.messages = [("assistant", INTRO)]
        st.rerun()
    st.divider()
    st.caption(f"Model: `{llm_client.model_name()}`")

if "session" not in st.session_state:
    st.session_state.session = GameSession()
    st.session_state.messages = [("assistant", INTRO)]

if not llm_client.is_configured():
    st.error(
        "No API key found. Copy `.env.example` to `.env`, add your free Gemini key "
        "(GEMINI_API_KEY) and restart the app."
    )
    st.stop()

for role, text in st.session_state.messages:
    with st.chat_message(role):
        st.markdown(text)

session: GameSession = st.session_state.session

if session.escaped:
    st.success("🎉 You escaped the library! Press **Restart game** to play again.")
elif prompt := st.chat_input("What do you do?"):
    prompt = prompt.strip()[:500]
    st.session_state.messages.append(("user", prompt))
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        try:
            with st.spinner("The Game Master is thinking..."):
                reply = session.send(prompt)
            st.markdown(reply)
            st.session_state.messages.append(("assistant", reply))
        except Exception as exc:  # noqa: BLE001
            st.session_state.messages.pop()  # drop the unanswered player message
            st.error(f"The Game Master could not respond: {exc}")
    if session.escaped:
        st.balloons()
        st.success("🎉 You escaped the library! Press **Restart game** to play again.")
