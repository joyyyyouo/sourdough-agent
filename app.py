import base64
import datetime
import os
import sqlite3
import uuid
from pathlib import Path

import streamlit as st

import infra.db as db_module
from assistant_names import generate_assistant_name
from config import DB_PATH
from service import BakingAgentService


def _now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


st.set_page_config(page_title="Couch to Crust", page_icon="🍞", layout="wide")

# ---------------------------------------------------------------------------
# Theme — warm earthy palette, handwritten headings, soft rounded UI
# ---------------------------------------------------------------------------
st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Caveat:wght@400;600;700&family=Lato:wght@300;400;500&display=swap');

/* ── Global ──────────────────────────────────────────────────────── */
html, body,
[data-testid="stAppViewContainer"],
[data-testid="stMain"] {
    background-color: #FDF6EC !important;
    color: #3D2B1F;
    font-family: 'Lato', 'Segoe UI', sans-serif;
}

/* ── Headings ─────────────────────────────────────────────────────── */
h1, h2, h3,
[data-testid="stMarkdownContainer"] h1,
[data-testid="stMarkdownContainer"] h2,
[data-testid="stMarkdownContainer"] h3 {
    font-family: 'Caveat', cursive !important;
    color: #7A5C3A !important;
    font-weight: 600 !important;
    letter-spacing: 0.5px;
}

/* ── Hero banner placeholder ──────────────────────────────────────── */
.hero-banner {
    width: 100%;
    height: 180px;
    background: linear-gradient(135deg, #EDD9B8 0%, #C8873A 55%, #7A5C3A 100%);
    border-radius: 20px;
    margin-bottom: 0.5rem;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 12px;
    font-family: 'Lato', sans-serif;
    font-size: 0.95rem;
    font-weight: 500;
    color: rgba(253,246,236,0.85);
    letter-spacing: 1px;
    border: 2px dashed rgba(253,246,236,0.4);
    cursor: default;
    user-select: none;
}
.hero-banner svg {
    opacity: 0.7;
}

/* ── Sidebar ──────────────────────────────────────────────────────── */
[data-testid="stSidebar"] {
    background-color: #F5EAD8 !important;
    border-right: 1px solid #E8D5C0 !important;
}
[data-testid="stSidebar"] label {
    font-family: 'Lato', sans-serif;
    color: #7A5C3A !important;
    font-weight: 500;
}

/* ── Text inputs & chat input ─────────────────────────────────────── */
[data-testid="textInput"] input {
    border-radius: 14px !important;
    border: 1.5px solid #C4A882 !important;
    background-color: #FFFBF5 !important;
    color: #3D2B1F !important;
}
[data-testid="textInput"] input:focus {
    border-color: #C8873A !important;
    box-shadow: 0 0 0 2px rgba(200,135,58,0.18) !important;
}
[data-testid="stChatInput"] textarea {
    border-radius: 18px !important;
    border: 1.5px solid #C4A882 !important;
    background-color: #FFFBF5 !important;
    color: #3D2B1F !important;
    font-family: 'Lato', sans-serif !important;
}
[data-testid="stChatInput"] textarea:focus {
    border-color: #C8873A !important;
    box-shadow: 0 0 0 2px rgba(200,135,58,0.18) !important;
}

/* ── Chat message bubbles ─────────────────────────────────────────── */
[data-testid="stChatMessage"] {
    border-radius: 18px !important;
    padding: 12px 18px !important;
    margin-bottom: 6px !important;
    box-shadow: 0 1px 5px rgba(122,92,58,0.07) !important;
}

/* ── Buttons ──────────────────────────────────────────────────────── */
[data-testid="stButton"] > button {
    border-radius: 999px !important;
    background-color: #C8873A !important;
    color: #FDF6EC !important;
    border: none !important;
    font-family: 'Lato', sans-serif !important;
    font-weight: 500 !important;
    padding: 0.45rem 1.5rem !important;
    transition: background-color 0.2s ease !important;
}
[data-testid="stButton"] > button:hover {
    background-color: #7A5C3A !important;
    color: #FDF6EC !important;
}

/* ── Summary table card ───────────────────────────────────────────── */
[data-testid="stTable"] {
    border-radius: 16px !important;
    overflow: hidden !important;
    border: 1px solid #E8D5C0 !important;
    box-shadow: 0 2px 14px rgba(122,92,58,0.1) !important;
}
[data-testid="stTable"] table {
    background-color: #FFFBF5 !important;
    border-collapse: collapse !important;
    width: 100% !important;
}
[data-testid="stTable"] thead th {
    background-color: #F0E2CE !important;
    color: #7A5C3A !important;
    font-family: 'Lato', sans-serif !important;
    font-weight: 500 !important;
    padding: 10px 18px !important;
    border-bottom: 1px solid #E8D5C0 !important;
}
[data-testid="stTable"] tbody td {
    background-color: #FFFBF5 !important;
    color: #3D2B1F !important;
    padding: 10px 18px !important;
    border-top: 1px solid #F5EAD8 !important;
    font-family: 'Lato', sans-serif !important;
}

/* ── Alert / info boxes ───────────────────────────────────────────── */
[data-testid="stNotification"],
div[class*="stAlert"] {
    border-radius: 14px !important;
}

/* ── Status widget (Baking a plan spinner) ────────────────────────── */
[data-testid="stStatus"] {
    border-radius: 14px !important;
    border: 1px solid #E8D5C0 !important;
    background-color: #FFFBF5 !important;
    font-family: 'Lato', sans-serif !important;
}
</style>
""",
    unsafe_allow_html=True,
)
st.title("Couch to Crust")
# Hero banner — reads .streamlit/app_banner.png; falls back to a gradient placeholder
_banner_path = Path(".streamlit/app_banner.png")
if _banner_path.exists():
    _b64 = base64.b64encode(_banner_path.read_bytes()).decode()
    st.markdown(
        f'<img src="data:image/png;base64,{_b64}" '
        f'style="width:100%;height:180px;object-fit:cover;'
        f'border-radius:20px;margin-bottom:0.5rem;display:block;" />',
        unsafe_allow_html=True,
    )
else:
    st.markdown(
        """
<div class="hero-banner">
    <svg width="28" height="28" viewBox="0 0 24 24" fill="none"
         stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
        <rect x="3" y="3" width="18" height="18" rx="4"/>
        <circle cx="8.5" cy="8.5" r="1.5"/>
        <polyline points="21 15 16 10 5 21"/>
    </svg>
    Add your banner image here
</div>
""",
        unsafe_allow_html=True,
    )


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
# Service — one instance per server process, shared across all sessions
# ---------------------------------------------------------------------------
@st.cache_resource
def _get_service() -> BakingAgentService:
    return BakingAgentService()


service = _get_service()

# ---------------------------------------------------------------------------
# Session initialisation — persistent across browser sessions via URL param
# ---------------------------------------------------------------------------
if "thread_id" not in st.session_state:
    session_key = st.query_params.get("s")
    session_row = None

    if session_key:
        conn = db_module.init_db(DB_PATH)
        session_row = db_module.get_user_session(conn, session_key)
        conn.close()

    if session_row:
        # Returning user — restore from existing checkpoint
        thread_id = session_row["thread_id"]
        bot_name = session_row["bot_name"]

        # Verify the checkpoint actually exists (defensive guard)
        if not service.checkpoint_exists(thread_id):
            session_row = None  # fall through to new session

    if not session_row:
        # New user (or expired/invalid session key)
        session_key = str(uuid.uuid4())
        thread_id = str(uuid.uuid4())
        bot_name = generate_assistant_name()
        now = _now_iso()

        conn = db_module.init_db(DB_PATH)
        db_module.upsert_user_session(conn, session_key, thread_id, bot_name, now, now)
        conn.close()

        st.query_params["s"] = session_key

        # Seed the agent so the assistant generates its opening message
        service.seed(
            thread_id,
            {
                "bot_name": bot_name,
                "session_key": session_key,
            },
        )

    st.session_state.thread_id = thread_id
    st.session_state.bot_name = bot_name
    st.session_state.session_key = session_key

# ---------------------------------------------------------------------------
# Chat messages
# ---------------------------------------------------------------------------
state_values = service.get_state(st.session_state.thread_id)

for msg in state_values.get("messages", []):
    role = msg.get("role") if isinstance(msg, dict) else None
    if role not in ("user", "assistant"):
        continue
    text = msg.get("content", "") if isinstance(msg, dict) else ""
    if not text:
        continue
    avatar = "🍞" if role == "assistant" else "☕"
    with st.chat_message(role, avatar=avatar):
        st.markdown(text)

if state_values.get("intake_complete"):
    st.success(
        "Intake complete! Your baking session has been saved. Schedule generation coming soon."
    )  # noqa: E501

# ---------------------------------------------------------------------------
# Chat input – at top level to pin to bottom of page
# ---------------------------------------------------------------------------
if not state_values.get("intake_complete"):
    if user_text := st.chat_input("Type your answer here..."):
        with st.chat_message("user", avatar="☕"):
            st.markdown(user_text)

        with st.spinner("Thinking..."):
            updated = service.send_message(st.session_state.thread_id, user_text)

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

        response_text = updated.get("_response", "")
        if response_text:
            with st.chat_message("assistant", avatar="🍞"):
                st.markdown(response_text)

        if updated.get("intake_complete"):
            st.rerun()
