import datetime

from pydantic import BaseModel, Field

# System prompt for SUBSEQUENT turns in the commit stage (after the initial schedule
# presentation has already been sent directly by the engine).
_SYSTEM_TEMPLATE = """\
You are {bot_name}, a warm and knowledgeable sourdough baking assistant.

The baking schedule has already been presented to the user.
Today (Melbourne time) is {today}.

## Schedule (reference)
```
{schedule_table}
```

Guidelines:
- If the user says yes / confirms / agrees, call `CommitPlan` immediately.
- If the user gives a different target time, extract it as ISO-8601 and call `UpdateDeadline`.
- If the user mentions they are unavailable during a time window (e.g. "I have dinner \
from 7–9pm"), call `ReportConflict` with ISO-8601 from/to windows.
- Only answer questions about steps or the schedule when explicitly asked. \
Do not volunteer explanations unprompted.
- Stay strictly on topic.
"""


class CommitPlan(BaseModel):
    """Call this when the user confirms they are happy to proceed with the bake plan."""


class UpdateDeadline(BaseModel):
    """Call this when the user wants to aim for a different target time."""

    new_deadline_iso: str = Field(
        description="The revised target datetime in ISO-8601 format. E.g. '2026-05-26T19:00:00'."
    )


class ConflictWindow(BaseModel):
    from_iso: str = Field(description="Start of unavailable window in ISO-8601.")
    to_iso: str = Field(description="End of unavailable window in ISO-8601.")
    reason: str | None = Field(default=None, description="Optional description, e.g. 'dinner'.")


class ReportConflict(BaseModel):
    """Call when the user flags one or more windows where they are unavailable."""

    windows: list[ConflictWindow]


_llm = None


def get_llm():
    global _llm
    if _llm is None:
        from llm import make_llm

        _llm = make_llm([CommitPlan, UpdateDeadline, ReportConflict])
    return _llm


def _fmt_time(iso: str) -> str:
    return datetime.datetime.fromisoformat(iso).strftime("%a %H:%M")


def _step_clashes_any(step: dict, conflicts: list[dict]) -> str | None:
    """Return the reason of the first conflict that clashes with step, or None."""
    step_start = datetime.datetime.fromisoformat(step["start_iso"])
    step_end = step_start + datetime.timedelta(minutes=max(step.get("duration_min") or 0, 1))
    for c in conflicts:
        c_start = datetime.datetime.fromisoformat(c["from_iso"].replace("Z", "+00:00")).replace(
            tzinfo=None
        )
        c_end = datetime.datetime.fromisoformat(c["to_iso"].replace("Z", "+00:00")).replace(
            tzinfo=None
        )
        if step_start < c_end and step_end > c_start:
            return c.get("reason") or "your unavailability window"
    return None


_STEP_LABELS = {
    "sf_1": "S&F set 1",
    "sf_2": "S&F set 2",
    "sf_3": "S&F set 3",
    "sf_4": "S&F set 4",
    "bench_rest": "Bench rest",
}


def build_commit_message(state) -> str:
    """Construct the initial commit-stage presentation directly from state (no LLM).

    Structure:
        ```schedule table```

        [Case B] ⚠️ monitoring warning
        [Case C] ⚠️ deadline-miss one-liner
        [conflict re-plan] ℹ️ skipped-step notes
        [hard clash] ⚠️ clash warnings

        Closing question
    """
    from engine.stages.plan import format_schedule

    table = format_schedule(state.schedule)
    delta = state.plan_deadline_delta_min or 0
    adjustments = state.plan_adjustments or {}
    flexibility = state.intake.get("deadline_flexibility", "firm")
    enjoy_iso = state.plan_enjoy_iso
    deadline_iso = state.intake.get("deadline", "")
    conflicts = state.conflicts or []
    skipped_steps = getattr(state, "plan_skipped_steps", [])

    within_window = abs(delta) <= 30
    high_impact = adjustments.get("warm_water_bulk") or adjustments.get("room_temp_proof")

    parts: list[str] = [f"```\n{table}\n```"]

    if not within_window:
        # Case C — deadline miss
        enjoy_display = _fmt_time(enjoy_iso) if enjoy_iso else "unknown"
        deadline_display = _fmt_time(deadline_iso) if deadline_iso else "your target"
        direction = "late" if delta > 0 else "early"
        parts.append(
            f"⚠️ Best I can do is finish the bake at {enjoy_display} — "
            f"{abs(delta)} min {direction} your target of {deadline_display}."
        )
    elif high_impact:
        # Case B — met deadline via accelerated techniques
        techniques = []
        if adjustments.get("warm_water_bulk"):
            techniques.append("warm water bulk")
        if adjustments.get("room_temp_proof"):
            techniques.append("room-temp proof")
        tech_str = " + ".join(techniques)
        warning = (
            f"⚠️ Needs close monitoring — uses {tech_str}, so timing is more sensitive than usual."
        )
        if flexibility == "flexible":
            warning += " A later target would make for a more relaxed bake."
        parts.append(warning)

    # Skipped-step notes from conflict re-plan
    # TODO: personalise verbosity by user_experience_level
    # (beginner = silent, intermediate/experienced = show note)
    if skipped_steps and conflicts:
        for step_id in skipped_steps:
            label = _STEP_LABELS.get(step_id, step_id)
            parts.append(f"ℹ️ {label} skipped — clashed with your unavailability window.")

    # Hard-clash warnings: active non-skippable steps that still overlap a conflict window
    if conflicts and state.schedule:
        for step in state.schedule:
            if step.get("active") and not step.get("skippable"):
                reason = _step_clashes_any(step, conflicts)
                if reason:
                    parts.append(
                        f"⚠️ {step['label']} at {_fmt_time(step['start_iso'])} still clashes"
                        f" with {reason}. Adjust your start time, deadline, or availability?"
                    )

    # Closing question
    if not within_window:
        parts.append("Want to try a different finish time, or shall I go with this plan?")
    else:
        parts.append("Ready to lock this in? Let me know if any steps clash with your schedule.")

    return "\n\n".join(parts)


def build_system(bot_name: str, state) -> str:
    from zoneinfo import ZoneInfo

    from engine.stages.plan import format_schedule

    table = format_schedule(state.schedule)
    today = datetime.datetime.now(ZoneInfo("Australia/Melbourne")).strftime("%Y-%m-%dT%H:%M:%S")
    return _SYSTEM_TEMPLATE.format(
        bot_name=bot_name,
        schedule_table=table,
        today=today,
    )
