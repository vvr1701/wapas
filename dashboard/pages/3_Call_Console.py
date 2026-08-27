"""Screen 3 — Call console (FR-7.1): text-mode chat against the real policy +
live Claude; audio mode lives in the FastAPI console (mic capture)."""

import streamlit as st

from channels.voice.call_agent import claude_conversation
from channels.voice.policy import CallFacts, CallSession, respond

st.set_page_config(page_title="Wapas · Call console", page_icon="🪃")
st.title("Hinglish call console — text mode")
st.caption(
    "Same conversation policy and rails as the voice call. For the full "
    "mic → Sarvam STT → Claude → Sarvam TTS loop, run: "
    "`uv run uvicorn channels.voice.console:app` and open http://localhost:8000"
)

if "call" not in st.session_state:
    st.session_state.call = CallSession(
        facts=CallFacts(
            case_id=0,
            customer_id="cust_demo",
            customer_name="Vikram Singh",
            amount_inr=18000,
            due_date="2026-08-17",
            today="2026-08-27",
        )
    )

call = st.session_state.call
for t in call.transcript:
    with st.chat_message("user" if t["role"] == "customer" else "assistant"):
        st.write(t["text"])

if call.ended:
    st.info("Call ended by policy. Refresh the page to start a new call.")
elif text := st.chat_input("Customer says… (try: 'salary 1 tarikh ko aayegi' or 'call mat karo')"):
    turn = respond(call, text, claude_conversation(None))
    st.rerun()
