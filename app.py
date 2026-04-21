import datetime
import os
import sqlite3
import uuid

import streamlit as st
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

import db as db_module
from config import DB_PATH
from graph import build_graph
from nodes.intake import random_name


def _text(msg) -> str:
    """Extract plain text from a LangChain message, handling Gemini's list-of-blocks format."""
    content = msg.content
    if isinstance(content, str):
        return content
    return "".join(
        block.get("text", "") if isinstance(block, dict) else str(block)
        for block in content
    )


def _now_iso() -> str:
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


st.set_page_config(page_title="Sourdough Scheduler", page_icon="🍞", layout="wide")
st.title("Sourdough Baking Assistant")

# ---------------------------------------------------------------------------
# API key input
# ---------------------------------------------------------------------------
with st.sidebar:
    api_key = st.text_input("Google API Key", type="password")

if not api_key:
    st.info("Enter your Google API key in the sidebar to get started.")
    st.stop()

os.environ["GOOGLE_API_KEY"] = api_key

# ---------------------------------------------------------------------------
# Session initialisation — persistent across browser sessions via URL param
# ---------------------------------------------------------------------------
if "graph" not in st.session_state:
    checkpointer = SqliteSaver.from_conn_string(DB_PATH)

    session_key = st.query_params.get("s")
    session_row = None

    if session_key:
        conn = sqlite3.connect(DB_PATH)
        db_module.init_db(DB_PATH)  # ensure schema is up to date
        session_row = db_module.get_user_session(conn, session_key)
        conn.close()

    if session_row:
        # Returning user — restore from existing checkpoint
        thread_id = session_row["thread_id"]
        bot_name = session_row["bot_name"]
        graph = build_graph(checkpointer)

        # Verify the checkpoint actually exists (defensive guard)
        snapshot = graph.get_state({"configurable": {"thread_id": thread_id}})
        if not snapshot or not snapshot.values:
            session_row = None  # fall through to new session

    if not session_row:
        # New user (or expired/invalid session key)
        session_key = str(uuid.uuid4())
        thread_id = str(uuid.uuid4())
        bot_name = random_name()
        now = _now_iso()

        graph = build_graph(checkpointer)

        conn = sqlite3.connect(DB_PATH)
        db_module.init_db(DB_PATH)
        db_module.upsert_user_session(conn, session_key, thread_id, bot_name, now, now)
        conn.close()

        st.query_params["s"] = session_key

        # Seed the graph so the assistant generates its opening message
        graph.invoke(
            {
                "messages": [],
                "readiness_complete": False,
                "user_experience_level": None,
                "intake": {},
                "intake_complete": False,
                "bake_session_id": None,
                "schedule": None,
                "conflicts": None,
                "current_node": "assess_readiness",
                "bot_name": bot_name,
                "session_key": session_key,
                "bake_phase": "planning",
                "completed_steps": [],
                "weather_scraped_at": None,
                "weather_scrape_run_id": None,
                "diagnosis": None,
                "revision_type": None,
            },
            config={"configurable": {"thread_id": thread_id}},
        )

    st.session_state.graph = graph
    st.session_state.thread_id = thread_id
    st.session_state.bot_name = bot_name
    st.session_state.session_key = session_key

thread_cfg = {"configurable": {"thread_id": st.session_state.thread_id}}

# ---------------------------------------------------------------------------
# Chat messages
# ---------------------------------------------------------------------------
snapshot = st.session_state.graph.get_state(thread_cfg)
state_values = snapshot.values

for msg in state_values.get("messages", []):
    if msg.type not in ("human", "ai"):
        continue
    if getattr(msg, "tool_calls", None):
        continue
    text = _text(msg)
    if not text:
        continue
    role = "assistant" if msg.type == "ai" else "user"
    with st.chat_message(role):
        st.markdown(text)

if state_values.get("intake_complete"):
    st.success("Intake complete! Your baking session has been saved. Schedule generation coming soon.")

# ---------------------------------------------------------------------------
# Chat input – at top level to pin to bottom of page
# ---------------------------------------------------------------------------
if not state_values.get("intake_complete"):
    if user_text := st.chat_input("Type your answer here..."):
        with st.chat_message("user"):
            st.markdown(user_text)

        with st.spinner("Thinking..."):
            # If the graph is paused at an interrupt(), resume it; otherwise
            # inject a new message (the existing pattern for assess_readiness/intake)
            current_snapshot = st.session_state.graph.get_state(thread_cfg)
            if current_snapshot.next:
                updated = st.session_state.graph.invoke(
                    Command(resume=user_text),
                    config=thread_cfg,
                )
            else:
                updated = st.session_state.graph.invoke(
                    {"messages": [{"role": "user", "content": user_text}]},
                    config=thread_cfg,
                )

        # Update last_seen_at on every interaction
        now = _now_iso()
        conn = sqlite3.connect(DB_PATH)
        db_module.upsert_user_session(
            conn,
            st.session_state.session_key,
            st.session_state.thread_id,
            st.session_state.bot_name,
            now,
            now,
        )
        conn.close()

        last_ai = next(
            (
                m for m in reversed(updated["messages"])
                if m.type == "ai" and not getattr(m, "tool_calls", None) and _text(m)
            ),
            None,
        )
        if last_ai:
            with st.chat_message("assistant"):
                st.markdown(_text(last_ai))

        if updated.get("intake_complete"):
            st.rerun()
