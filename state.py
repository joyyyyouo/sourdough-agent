import operator
from typing import Annotated, Literal, Optional
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages


class BakeIntake(TypedDict, total=False):
    starter_health: str
    deadline: str       # ISO-8601 UTC
    last_fed_at: str    # ISO-8601 UTC
    feeding_ratio: str  # e.g. "1:1:1"


class BakeStep(TypedDict, total=False):
    step_id: int
    step_time: str           # ISO-8601 UTC
    step_label: str
    duration_minutes: Optional[int]
    notes: Optional[str]
    completed: bool
    completed_at: Optional[str]  # ISO-8601 UTC


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    readiness_complete: bool
    user_experience_level: Optional[str]  # "beginner" | "some_experience" | "experienced"
    intake: BakeIntake
    intake_complete: bool
    bake_session_id: Optional[int]
    schedule: Optional[list]   # list[BakeStep]
    conflicts: Optional[list]
    current_node: Literal[
        "assess_readiness", "intake", "scheduler", "commitment",
        "revision", "bake_monitor", "diagnostic", "end"
    ]
    bot_name: Optional[str]

    # Session linkage
    session_key: Optional[str]   # links to user_sessions.session_key in DB

    # Bake lifecycle
    bake_phase: Literal["planning", "monitoring", "complete"]
    # Accumulates step IDs as user checks them off; uses operator.add so nodes
    # append without clobbering earlier entries (same pattern as messages)
    completed_steps: Annotated[list, operator.add]

    # Weather tracking — used to detect stale forecasts mid-bake
    weather_scraped_at: Optional[str]      # ISO-8601 UTC
    weather_scrape_run_id: Optional[int]

    # Diagnostic output — set by diagnostic node, consumed by revision
    diagnosis: Optional[str]
    revision_type: Optional[str]  # "weather_change" | "timing" | "technique"
