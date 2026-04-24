import datetime
import sqlite3

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END
from pydantic import BaseModel, Field

import db as db_module
from config import DB_PATH
from llm import make_llm
from nodes.utils import clean_history
from state import AgentState, Node


class SubmitIntake(BaseModel):
    """Call this ONLY when all four fields have been confirmed by the user.
    Do not guess any field."""

    starter_health: str = Field(
        description=(
            "How active/healthy the starter is right now."
            " E.g. 'very active – doubled in 4 hours', 'sluggish – barely rose'."
        )
    )
    deadline: str = Field(
        description=(
            "ISO-8601 datetime when the user wants a freshly baked loaf."
            " E.g. '2026-04-22T09:00:00'."
        )
    )
    last_fed_at: str = Field(
        description="ISO-8601 datetime of the starter's last feeding. E.g. '2026-04-21T07:00:00'."
    )
    feeding_ratio: str = Field(
        description="Starter:flour:water ratio used when feeding. E.g. '1:1:1' or '1:5:5'."
    )


INTAKE_SYSTEM_PROMPT = """\
You are {bot_name}, a warm and knowledgeable sourdough baking assistant. \
The user has already been welcomed and confirmed they are ready to bake. \
Do not re-introduce yourself.

Your goal is to gather four pieces of information through natural conversation:

1. **starter_health** – how active/healthy their sourdough starter is right now
2. **deadline** – when they want the loaf freshly baked and ready to eat
3. **last_fed_at** – when they last fed their starter
4. **feeding_ratio** – the ratio they use when feeding (e.g. 1:1:1 or 1:5:5)

Guidelines:
- Stay strictly on topic. Do not engage in small talk, answer unrelated questions, \
or go off on tangents. If the user says something unrelated, politely redirect them \
back to the intake questions.
- Ask one or two questions at a time; don't overwhelm the user with a wall of text.
- Always give examples or options to open-ended questions to help beginners answer \
more precisely.
- If the user gives a relative time like "this morning" or "tomorrow breakfast", \
clarify and convert to an explicit date and time. Today (UTC) is {today}.
- Once you have all four fields confirmed, call the `submit_intake` tool. \
Do not call it until you are sure about every field.\
"""

_llm = None


def _get_llm():
    global _llm
    if _llm is None:
        _llm = make_llm([SubmitIntake])
    return _llm


def collect_bake_context_node(state: AgentState, config: RunnableConfig) -> dict:
    # Already done — pass through so the conditional edge routes to estimate_timeline
    if state.get("intake_complete"):
        return {}

    today = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    bot_name = state.get("bot_name") or "Doughy"
    system = INTAKE_SYSTEM_PROMPT.format(today=today, bot_name=bot_name)

    # Slice to messages after the SubmitReadiness tool call so the intake LLM
    # only sees intake-phase context, not the preceding readiness conversation.
    all_msgs = state["messages"]
    last_tool_idx = max(
        (i for i, m in enumerate(all_msgs) if getattr(m, "tool_calls", None)),
        default=-1,
    )
    intake_msgs = all_msgs[last_tool_idx + 1 :]
    history = clean_history(intake_msgs, seed="Hi, I'd like to plan a sourdough bake.")
    response = _get_llm().invoke([{"role": "system", "content": system}] + history)

    tool_calls = getattr(response, "tool_calls", []) or []
    submit_call = next((tc for tc in tool_calls if tc["name"] == SubmitIntake.__name__), None)

    if submit_call:
        intake_data: dict = submit_call["args"]
        thread_id = config.get("configurable", {}).get("thread_id")
        conn = sqlite3.connect(DB_PATH)
        session_id = db_module.insert_bake_session(
            conn,
            created_at=today,
            starter_health=intake_data["starter_health"],
            deadline=intake_data["deadline"],
            last_fed_at=intake_data["last_fed_at"],
            feeding_ratio=intake_data["feeding_ratio"],
            thread_id=thread_id,
        )
        # Link the DB bake record back to the user session
        session_key = state.get("session_key")
        if not session_key:
            raise ValueError("collect_bake_context_node: session_key missing from state")
        db_module.update_session_bake_data(conn, session_key, session_id, "planning")
        conn.close()

        return {
            "messages": [response],
            "intake": intake_data,
            "intake_complete": True,
            "bake_session_id": session_id,
        }

    return {
        "messages": [response],
    }


def route_after_collect_bake_context(state: AgentState) -> str:
    if state.get("intake_complete"):
        return Node.ESTIMATE_TIMELINE
    return END
