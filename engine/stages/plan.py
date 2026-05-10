import datetime

from config import (
    PLAN_BENCH_REST_DURATION_MIN,
    PLAN_BULK_FERMENT_DURATION_MIN,
    PLAN_BULK_FERMENT_MAX_MIN,
    PLAN_BULK_FERMENT_MIN_MIN,
    PLAN_BULK_FERMENT_Q10,
    PLAN_BULK_FERMENT_REFERENCE_TEMP_C,
    PLAN_MIX_DURATION_MIN,
    PLAN_PROOF_DURATION_MIN,
    PLAN_SF_ACTIVE_MIN,
    PLAN_SF_COUNT,
    PLAN_SF_INTERVAL_MIN,
    PLAN_SHAPING_DURATION_MIN,
)


def calc_bulk_ferment_duration(weather_weighted_temps: dict | None) -> int:
    """Return bulk fermentation duration in minutes, adjusted for temperature.

    Uses the Q10 biological model: fermentation rate doubles per 10°C increase.
    Averages hour_0 and hour_2 temps — both fall within the bulk fermentation window.
    Falls back to the config default if no temperature data is available.
    """
    temps = [
        v
        for k, v in (weather_weighted_temps or {}).items()
        if k in ("hour_0", "hour_2") and v is not None
    ]
    if not temps:
        return PLAN_BULK_FERMENT_DURATION_MIN

    avg_temp = sum(temps) / len(temps)
    adjusted = PLAN_BULK_FERMENT_DURATION_MIN * (
        PLAN_BULK_FERMENT_Q10 ** ((PLAN_BULK_FERMENT_REFERENCE_TEMP_C - avg_temp) / 10)
    )
    return max(PLAN_BULK_FERMENT_MIN_MIN, min(PLAN_BULK_FERMENT_MAX_MIN, round(adjusted)))


def build_schedule(state) -> list[dict]:
    """Compute a deterministic bake schedule from intake data and config durations."""
    start_iso = state.intake["earliest_start_time"]
    cursor = datetime.datetime.fromisoformat(start_iso.replace("Z", "+00:00"))

    bulk_min = calc_bulk_ferment_duration(state.weather_weighted_temps)

    steps = []

    # The big mix
    steps.append(
        {
            "step_id": "big_mix",
            "label": "The big mix",
            "start_iso": cursor.isoformat(),
            "duration_min": PLAN_MIX_DURATION_MIN,
            "substep": False,
        }
    )
    cursor += datetime.timedelta(minutes=PLAN_MIX_DURATION_MIN)

    # Bulk fermentation (parent step)
    bulk_start = cursor
    steps.append(
        {
            "step_id": "bulk_ferment",
            "label": "Bulk fermentation",
            "start_iso": cursor.isoformat(),
            "duration_min": bulk_min,
            "substep": False,
        }
    )

    # Stretch & fold sub-steps inside bulk fermentation
    sf_cursor = bulk_start + datetime.timedelta(minutes=PLAN_SF_INTERVAL_MIN)
    for i in range(1, PLAN_SF_COUNT + 1):
        steps.append(
            {
                "step_id": f"sf_{i}",
                "label": f"Stretch & fold set {i}",
                "start_iso": sf_cursor.isoformat(),
                "duration_min": PLAN_SF_ACTIVE_MIN,
                "substep": True,
            }
        )
        sf_cursor += datetime.timedelta(minutes=PLAN_SF_INTERVAL_MIN)

    cursor += datetime.timedelta(minutes=bulk_min)

    # Shaping
    steps.append(
        {
            "step_id": "shaping",
            "label": "Shaping",
            "start_iso": cursor.isoformat(),
            "duration_min": PLAN_SHAPING_DURATION_MIN,
            "substep": False,
        }
    )
    cursor += datetime.timedelta(minutes=PLAN_SHAPING_DURATION_MIN)

    # Bench rest
    steps.append(
        {
            "step_id": "bench_rest",
            "label": "Bench rest",
            "start_iso": cursor.isoformat(),
            "duration_min": PLAN_BENCH_REST_DURATION_MIN,
            "substep": False,
        }
    )
    cursor += datetime.timedelta(minutes=PLAN_BENCH_REST_DURATION_MIN)

    # Proof (cold)
    steps.append(
        {
            "step_id": "proof",
            "label": "Proof (cold)",
            "start_iso": cursor.isoformat(),
            "duration_min": PLAN_PROOF_DURATION_MIN,
            "substep": False,
        }
    )

    return steps


def _fmt_duration(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes} min"
    h, m = divmod(minutes, 60)
    return f"{h}h {m}m" if m else f"{h}h"


def _fmt_time(iso: str) -> str:
    dt = datetime.datetime.fromisoformat(iso)
    return dt.strftime("%H:%M")


def format_schedule(schedule: list[dict]) -> str:
    """Return a fixed-width plain-text table suitable for a Telegram code block."""
    col_step = 24
    col_start = 8
    header = f"{'Step':<{col_step}} {'Start':<{col_start}} Duration"
    divider = "─" * (col_step + col_start + 10)
    lines = [header, divider]
    for step in schedule:
        indent = "  └ " if step.get("substep") else ""
        label = indent + step["label"]
        start = _fmt_time(step["start_iso"])
        dur = _fmt_duration(step["duration_min"])
        lines.append(f"{label:<{col_step}} {start:<{col_start}} {dur}")
    return "\n".join(lines)
