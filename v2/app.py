"""Streamlit UI for Version 2.  Run with:  streamlit run v2/app.py"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st  # noqa: E402

from common import llm_client  # noqa: E402
from v2.game_master import GameMaster  # noqa: E402

st.set_page_config(page_title="AI Escape Room - V2", page_icon="🔐", layout="wide")
st.title("🔐 AI Escape Room — Version 2 (Reliable)")
st.caption("Python owns the rules and the game state; the LLM only interprets and narrates.")


def new_game() -> None:
    gm = GameMaster()
    st.session_state.gm = gm
    st.session_state.messages = [("assistant", gm.intro)]
    st.session_state.last = None


if "gm" not in st.session_state:
    new_game()

gm: GameMaster = st.session_state.gm
pub = gm.engine.public_state()

with st.sidebar:
    st.header("How to play")
    st.markdown(
        "- Type what you want to do in plain English.\n"
        "- Examples: *examine the desk*, *take the magnifying glass*, "
        "*use the key on the door*, *try 1234 on the drawer*.\n"
        "- Say **hint**, **inventory** or **look around** at any time."
    )
    if st.button("🔄 Restart game", use_container_width=True):
        new_game()
        st.rerun()

    st.header("Game state")
    st.markdown(f"**Door:** {'🔓 open' if pub['door_status'] == 'open' else '🔒 locked'}")
    st.markdown("**Inventory:** " + (", ".join(pub["inventory"]) or "_empty_"))
    st.markdown("**Solved puzzles:**")
    for name in pub["solved_puzzles"] or ["_none yet_"]:
        st.markdown(f"- {name}")
    st.caption(f"Turn {pub['turn']}")

    if gm.use_llm:
        st.success(f"Gemini mode · `{llm_client.model_name()}`")
    else:
        st.warning("Offline mode: no `GEMINI_API_KEY` found, so a rule-based parser and plain narration are used. The game rules are identical.")

    with st.expander("🛠 Last engine decision (debug)"):
        st.json(st.session_state.last or {"info": "No action yet."})
    with st.expander("🛠 Full game state (JSON)"):
        st.code(json.dumps(gm.engine.state, indent=2), language="json")

for role, text in st.session_state.messages:
    with st.chat_message(role):
        st.markdown(text)

if gm.engine.state["escaped"]:
    st.success("🎉 You escaped the library! Press **Restart game** to play again.")
    if st.session_state.pop("celebrate", False):
        st.balloons()
elif prompt := st.chat_input("What do you do?"):
    prompt = prompt.strip()[:500]
    st.session_state.messages.append(("user", prompt))
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.spinner("The Game Master is thinking..."):
        out = gm.step(prompt)
    st.session_state.messages.append(("assistant", out["narration"]))
    st.session_state.last = {
        "player_text": prompt,
        "parsed_action": out["action"],
        "engine_result": {k: out["result"][k] for k in ("ok", "code", "state_changed")},
        "parser": out["parser"],
        "narrator": out["narrator"],
    }
    if out["escaped"]:
        st.session_state.celebrate = True
    st.rerun()
