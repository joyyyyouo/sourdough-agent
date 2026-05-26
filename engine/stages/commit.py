import datetime

from pydantic import BaseModel, Field

_SYSTEM_TEMPLATE = """\
You are {bot_name}, a warm and knowledgeable sourdough baking assistant.

You have just computed the best possible bake schedule for the user. \
Your job is to present it and get their commitment — or negotiate a new target time if needed.

## Schedule
```
{schedule_table}
```

## Step descriptions (use these when explaining what each step involves)
- **The big mix**: Combine starter, flour, water, and salt into a shaggy dough. \
No kneading yet — just bring it together.
- **Stretch & fold**: Every 30 minutes, stretch the dough up and fold it over itself \
(4 sides). Builds gluten strength without traditional kneading.
- **Bulk ferment**: Leave the dough covered at room temperature. \
Yeast and bacteria develop flavour and gas. The dough should grow noticeably.
- **Bench rest**: After shaping, rest the dough uncovered for a short time. \
Relaxes the gluten so the final shape holds.
- **Shape**: Gently form the dough into its final loaf shape and place in the banneton.
- **Proof (cold)**: Slow cold proof in the fridge. Develops flavour and makes \
the dough easier to score. Can be left overnight.
- **Proof (room temp)**: Faster proof at room temperature used when time is short. \
Requires more attention — don't let it over-proof.
- **Preheat**: Heat the Dutch oven in the oven to very high temperature. \
Critical for oven spring.
- **Score**: Slash the top of the loaf just before baking. \
Controls where the bread expands.
- **Bake (lid on)**: Steam trapped under the lid keeps the crust soft so the loaf \
can spring up fully.
- **Bake (lid off)**: Removing the lid lets the crust colour and crisp.
- **Rest**: Do not cut the loaf yet — the crumb is still setting inside. \
Cutting too early gives a gummy texture.
- **Enjoy!**: The loaf is ready to eat.

## Situation
{situation}

## Your task
{task}

Guidelines:
- Be warm and direct.
- If the user says yes / confirms / agrees, call `CommitPlan` immediately.
- If the user gives a different target time, extract it as an ISO-8601 datetime \
and call `UpdateDeadline`. Today (Melbourne time) is {today}.
- If the user asks what a step involves or why it's needed, explain it using \
the step descriptions above. Keep the explanation brief and practical.
- If the user asks to see the full schedule again, repeat the table above verbatim.
"""


class CommitPlan(BaseModel):
    """Call this when the user confirms they are happy to proceed with the bake plan."""


class UpdateDeadline(BaseModel):
    """Call this when the user wants to aim for a different target time."""

    new_deadline_iso: str = Field(
        description="The revised target datetime in ISO-8601 format. E.g. '2026-05-26T19:00:00'."
    )


_llm = None


def get_llm():
    global _llm
    if _llm is None:
        from llm import make_llm

        _llm = make_llm([CommitPlan, UpdateDeadline])
    return _llm


def _fmt_time(iso: str) -> str:
    return datetime.datetime.fromisoformat(iso).strftime("%a %H:%M")


def _build_situation_and_task(state) -> tuple[str, str]:
    """Return (situation, task) strings for the commit LLM system prompt.

    Case A — within deadline window (|delta| ≤ 30 min), no high-impact adjustments:
        Present the schedule and ask the user to commit.

    Case B — within deadline window but high-impact adjustments used
              (warm water bulk OR room-temperature proof):
        Warn that the bake needs close monitoring. If deadline_flexibility is
        'flexible', also suggest a later target for a more relaxed bake.

    Case C — outside deadline window (|delta| > 30 min):
        Report the closest achievable Enjoy! time and ask whether the user
        wants to adjust their target or proceed anyway.
    """
    delta = state.plan_deadline_delta_min or 0
    adjustments = state.plan_adjustments or {}
    flexibility = state.intake.get("deadline_flexibility", "firm")
    enjoy_iso = state.plan_enjoy_iso
    deadline_iso = state.intake.get("deadline", "")

    within_window = abs(delta) <= 30
    high_impact = adjustments.get("warm_water_bulk") or adjustments.get("room_temp_proof")

    if not within_window:
        enjoy_display = _fmt_time(enjoy_iso) if enjoy_iso else "an unknown time"
        deadline_display = _fmt_time(deadline_iso) if deadline_iso else "your target"
        direction = "late" if delta > 0 else "early"
        situation = (
            f"Unfortunately I couldn't find a plan that meets your target of {deadline_display}. "
            f"The closest I can get is Enjoy! at {enjoy_display} "
            f"({abs(delta)} min {direction})."
        )
        task = (
            "Explain this clearly and ask if they'd like to adjust their target time "
            "(call UpdateDeadline with the new time), or proceed with this schedule anyway "
            "(call CommitPlan)."
        )
    elif high_impact:
        techniques = []
        if adjustments.get("warm_water_bulk"):
            techniques.append("warm water bulk acceleration")
        if adjustments.get("room_temp_proof"):
            techniques.append("room temperature proof")
        tech_str = " and ".join(techniques)
        situation = (
            f"This schedule meets your target using {tech_str}. "
            "These techniques speed up fermentation but make timing more sensitive — "
            "you'll need to watch the dough closely rather than rely purely on the clock."
        )
        if flexibility == "flexible":
            task = (
                "Walk through the schedule step by step so the user knows what they're "
                "committing to. Note the techniques used and the need for close monitoring. "
                "Also mention that since their deadline has some flexibility, a slightly later "
                "target would allow a more relaxed, standard bake. "
                "Ask clearly: do they want to commit to this plan, or try a later time?"
            )
        else:
            task = (
                "Walk through the schedule step by step so the user knows what they're "
                "committing to. Note the techniques used and the need for close monitoring. "
                "Ask clearly: are they comfortable proceeding with this plan?"
            )
    else:
        situation = "This schedule comfortably meets your target."
        task = (
            "Walk through the schedule step by step so the user knows exactly what's ahead. "
            "Then ask clearly: are they ready to commit to this plan?"
        )

    return situation, task


def build_system(bot_name: str, state) -> str:
    from zoneinfo import ZoneInfo

    from engine.stages.plan import format_schedule

    table = format_schedule(state.schedule)
    situation, task = _build_situation_and_task(state)
    today = datetime.datetime.now(ZoneInfo("Australia/Melbourne")).strftime("%Y-%m-%dT%H:%M:%S")
    return _SYSTEM_TEMPLATE.format(
        bot_name=bot_name,
        schedule_table=table,
        situation=situation,
        task=task,
        today=today,
    )
