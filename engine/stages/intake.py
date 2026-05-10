import datetime
import sqlite3

from pydantic import BaseModel, Field

import infra.db as db_module
from config import DB_PATH
from llm import make_llm

SYSTEM_PROMPT = """\
You are {bot_name}, a warm and knowledgeable sourdough baking assistant. \
The user has already been welcomed and confirmed they are ready to bake. \
Do not re-introduce yourself.

Your goal is to gather five pieces of information through natural conversation:

1. **starter_health** – how active/healthy their sourdough starter is right now
2. **deadline** – when they want the loaf freshly baked and ready to eat
3. **last_fed_at** – when they last fed their starter
4. **feeding_ratio** – the ratio they use when feeding (e.g. 1:1:1 or 1:5:5)
5. **earliest_start_time** – the earliest moment they can begin the bake today

Guidelines:
- Stay strictly on topic. Do not engage in small talk, answer unrelated questions, \
or go off on tangents. If the user says something unrelated, politely redirect them \
back to the intake questions.
- Ask one or two questions at a time; don't overwhelm the user with a wall of text.
- Always give examples or options to open-ended questions to help beginners answer \
more precisely.
- If the user gives a relative time like "this morning" or "tomorrow breakfast", \
clarify and convert to an explicit date and time. Today (UTC) is {today}.
- Once you have all five fields confirmed, call the `SubmitIntake` tool. \
Do not call it until you are sure about every field.\
"""


class SubmitIntake(BaseModel):
    """Call this ONLY when all five fields have been confirmed by the user.
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
    earliest_start_time: str = Field(
        description=(
            "ISO-8601 datetime of the earliest moment the user can begin the bake."
            " E.g. '2026-04-21T08:00:00'."
        )
    )


_llm = None


def get_llm():
    global _llm
    if _llm is None:
        _llm = make_llm([SubmitIntake])
    return _llm


def build_system(bot_name: str) -> str:
    today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return SYSTEM_PROMPT.format(today=today, bot_name=bot_name)


def handle_submit(args: dict, session_key: str, thread_id: str | None) -> dict:
    """Insert bake_session to DB and return AgentState field updates."""
    today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = sqlite3.connect(DB_PATH)
    session_id = db_module.insert_bake_session(
        conn,
        created_at=today,
        starter_health=args["starter_health"],
        deadline=args["deadline"],
        last_fed_at=args["last_fed_at"],
        feeding_ratio=args["feeding_ratio"],
        earliest_start_time=args["earliest_start_time"],
        thread_id=thread_id,
    )
    if not session_key:
        raise ValueError("session_key missing from state during intake submission")
    db_module.update_session_bake_data(conn, session_key, session_id, "planning")
    conn.close()
    return {
        "intake": args,
        "intake_complete": True,
        "bake_session_id": session_id,
    }
