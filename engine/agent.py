"""Plain-Python agent loop — no LangGraph dependency.

Single entry point: agent_step(state, user_input) -> (state, response_text)

Stage machine:
  assess_readiness → collect_context → fetch_weather → plan → commit → guide → complete

fetch_weather is a synchronous auto-stage (no user input required); all others pause
and wait for the next user message before running.
"""

import dataclasses
import datetime
import json
from dataclasses import dataclass, field

import infra.db as db
from config import DB_PATH, WEATHER_DATA_STALE_THRESHOLD_S
from engine import weather as weather_module
from llm import make_llm

# ---------------------------------------------------------------------------
# Canonical state
# ---------------------------------------------------------------------------


@dataclass
class AgentState:
    stage: str = "assess_readiness"
    messages: list = field(default_factory=list)  # [{"role": "user"|"assistant", "content": str}]

    # stage boundary indices — maps stage name → index in messages where it started
    stage_boundaries: dict = field(default_factory=dict)

    # user context
    session_key: str | None = None
    thread_id: str | None = None
    bot_name: str | None = None
    user_experience_level: str | None = None

    # intake (5 fields collected during collect_context stage)
    intake: dict = field(default_factory=dict)
    intake_complete: bool = False

    # environment
    weather_scrape_run_id: int | None = None
    weather_scraped_at: str | None = None
    weather_weighted_temps: dict | None = None

    # plan
    schedule: list = field(default_factory=list)
    completed_steps: list = field(default_factory=list)
    conflicts: list = field(default_factory=list)

    # bake lifecycle
    bake_phase: str = "planning"  # planning | monitoring | complete
    bake_session_id: int | None = None
    readiness_complete: bool = False

    # diagnosis
    diagnosis: str | None = None
    revision_type: str | None = None

    def to_json(self) -> str:
        return json.dumps(dataclasses.asdict(self))

    @classmethod
    def from_json(cls, s: str) -> "AgentState":
        return cls(**json.loads(s))


# ---------------------------------------------------------------------------
# Stage transition (pure — no side effects)
# ---------------------------------------------------------------------------


def decide_next_stage(state: AgentState) -> str:
    """Return the next stage given current state. Pure function."""
    s = state.stage

    if s == "assess_readiness":
        return "collect_context" if state.readiness_complete else "assess_readiness"

    if s == "collect_context":
        return "fetch_weather" if state.intake_complete else "collect_context"

    if s == "fetch_weather":
        return "plan"

    if s == "plan":
        return "commit" if state.schedule else "plan"

    if s == "commit":
        return "guide" if not state.conflicts else "plan"

    if s == "guide":
        all_done = bool(state.schedule) and set(state.completed_steps) >= {
            step["step_id"] for step in state.schedule if "step_id" in step
        }
        return "complete" if all_done else "guide"

    return s


# ---------------------------------------------------------------------------
# Prompt construction (stage-aware)
# ---------------------------------------------------------------------------


def build_prompt(state: AgentState) -> list[dict]:
    """Return the full prompt list [system, ...history] for the current stage."""
    from engine.stages import intake, readiness

    bot_name = state.bot_name or "Doughy"

    if state.stage == "assess_readiness":
        system = readiness.build_system(bot_name)
        history = state.messages

    elif state.stage == "collect_context":
        system = intake.build_system(bot_name)
        start = state.stage_boundaries.get("collect_context", 0)
        history = state.messages[start:]

    else:
        system = f"You are {bot_name}, a sourdough baking assistant. Stage: {state.stage}"
        history = state.messages[-10:]

    if not history:
        history = [{"role": "user", "content": "Hi, I want to bake sourdough bread."}]

    return [{"role": "system", "content": system}] + history


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------


def _get_stage_llm(stage: str):
    from engine.stages import intake, readiness

    if stage == "assess_readiness":
        return readiness.get_llm()
    if stage == "collect_context":
        return intake.get_llm()
    return make_llm()


def _extract_text(response) -> str:
    """Handle Gemini's string or list-of-blocks content format."""
    content = response.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "") if isinstance(block, dict) else str(block) for block in content
        )
    return str(content)


def generate_response(state: AgentState) -> dict:
    """Call the LLM for the current stage and return {text, tool}."""
    llm = _get_stage_llm(state.stage)
    prompt = build_prompt(state)
    response = llm.invoke(prompt)

    text = _extract_text(response)
    tool_calls = getattr(response, "tool_calls", []) or []
    tool = tool_calls[0] if tool_calls else None

    return {"text": text, "tool": tool}


# ---------------------------------------------------------------------------
# State mutation from tool calls
# ---------------------------------------------------------------------------


def agent_brain(state: AgentState, llm_output: dict) -> AgentState:
    """Apply tool-call results to state. Single place for all state mutations."""
    from engine.stages import intake, readiness

    tool = llm_output.get("tool")
    if not tool:
        return state

    name = tool["name"]
    args = tool["args"]

    if state.stage == "assess_readiness" and name == "SubmitReadiness":
        updates = readiness.handle_submit(args)
        for k, v in updates.items():
            setattr(state, k, v)

    elif state.stage == "collect_context" and name == "SubmitIntake":
        updates = intake.handle_submit(args, state.session_key, state.thread_id)
        for k, v in updates.items():
            setattr(state, k, v)

    return state


# ---------------------------------------------------------------------------
# Automatic (non-LLM) stages
# ---------------------------------------------------------------------------


def _parse_iso(s: str) -> datetime.datetime:
    dt = datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt


def _do_fetch_weather(state: AgentState) -> AgentState:
    """Run the weather fetch synchronously and update state in place."""
    conn = db.init_db(DB_PATH)
    try:
        now = datetime.datetime.now(datetime.timezone.utc)
        now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")

        latest = db.get_latest_scrape_run(conn)
        stale = latest is None or (
            (now - _parse_iso(latest["scraped_at"])).total_seconds()
            > WEATHER_DATA_STALE_THRESHOLD_S
        )

        warning: str | None = None
        if stale:
            try:
                run_id = weather_module.fetch_and_save(conn, now_iso)
                scraped_at = now_iso
            except Exception:
                if latest:
                    run_id = latest["id"]
                    scraped_at = latest["scraped_at"]
                    hours_old = int((now - _parse_iso(scraped_at)).total_seconds() / 3600)
                    warning = (
                        f"⚠️ Couldn't fetch a fresh Melbourne weather forecast "
                        f"(data is {hours_old}h old). "
                        "Fermentation estimates may be slightly off."
                    )
                else:
                    run_id = None
                    scraped_at = None
                    warning = (
                        "⚠️ Couldn't fetch Melbourne weather data and no previous data exists. "
                        "Fermentation estimates may be less accurate."
                    )
        else:
            run_id = latest["id"]
            scraped_at = latest["scraped_at"]

        start_iso = state.intake.get("earliest_start_time")
        if run_id and start_iso:
            temps = weather_module.get_time_weighted_temps(conn, run_id, start_iso)
        else:
            temps = {"hour_0": None, "hour_2": None, "hour_5": None}

        if state.bake_session_id and run_id:
            db.update_bake_session_weather(
                conn,
                state.bake_session_id,
                run_id,
                temps.get("hour_0"),
                temps.get("hour_2"),
                temps.get("hour_5"),
            )

        state.weather_scrape_run_id = run_id
        state.weather_scraped_at = scraped_at
        state.weather_weighted_temps = temps

        if warning:
            state.messages.append({"role": "assistant", "content": warning})
    finally:
        conn.close()

    return state


def run_auto_stages(state: AgentState) -> AgentState:
    """Run stages that don't require user input (fetch_weather)."""
    while state.stage == "fetch_weather":
        state = _do_fetch_weather(state)
        next_stage = decide_next_stage(state)
        if next_stage != state.stage:
            state.stage_boundaries[next_stage] = len(state.messages)
        state.stage = next_stage
    return state


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def agent_step(state: AgentState, user_input: str) -> tuple[AgentState, str]:
    """One full agent cycle: observe → think → update state → advance stage → respond."""
    if user_input:
        state.messages.append({"role": "user", "content": user_input})

    llm_output = generate_response(state)
    state = agent_brain(state, llm_output)

    response_text = llm_output["text"]
    state.messages.append({"role": "assistant", "content": response_text})

    next_stage = decide_next_stage(state)
    if next_stage != state.stage:
        state.stage_boundaries[next_stage] = len(state.messages)
    state.stage = next_stage

    state = run_auto_stages(state)

    return state, response_text
