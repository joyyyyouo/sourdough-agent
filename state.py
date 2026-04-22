import operator
from typing import Annotated, Literal

from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


class BakeIntake(TypedDict, total=False):
    starter_health: str
    deadline: str  # ISO-8601 UTC
    last_fed_at: str  # ISO-8601 UTC
    feeding_ratio: str  # e.g. "1:1:1"


class BakeStep(TypedDict, total=False):
    step_id: int
    step_time: str  # ISO-8601 UTC
    step_label: str
    duration_minutes: int | None
    notes: str | None
    completed: bool
    completed_at: str | None  # ISO-8601 UTC


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    readiness_complete: bool
    user_experience_level: str | None  # "beginner" | "some_experience" | "experienced"
    intake: BakeIntake
    intake_complete: bool
    bake_session_id: int | None
    schedule: list[BakeStep] | None
    conflicts: list[dict] | None
    current_node: Literal[
        "assess_readiness",
        "intake",
        "scheduler",
        "commitment",
        "revision",
        "bake_monitor",
        "diagnostic",
        "end",
    ]
    bot_name: str | None

    # Session linkage
    session_key: str | None  # links to user_sessions.session_key in DB

    # Bake lifecycle
    bake_phase: Literal["planning", "monitoring", "complete"]
    # Accumulates step IDs as user checks them off; uses operator.add so nodes
    # append without clobbering earlier entries (same pattern as messages)
    completed_steps: Annotated[list, operator.add]

    # Weather tracking — used to detect stale forecasts mid-bake
    weather_scraped_at: str | None  # ISO-8601 UTC
    weather_scrape_run_id: int | None

    # Diagnostic output — set by diagnostic node, consumed by revision
    diagnosis: str | None
    revision_type: str | None  # "weather_change" | "timing" | "technique"
