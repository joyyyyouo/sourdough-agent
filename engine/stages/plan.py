import copy
import datetime
from zoneinfo import ZoneInfo

from config import (
    PLAN_BAKE_LID_OFF_MIN,
    PLAN_BAKE_LID_ON_MIN,
    PLAN_BENCH_REST_DURATION_MIN,
    PLAN_BULK_FERMENT_DURATION_MIN,
    PLAN_BULK_FERMENT_MAX_MIN,
    PLAN_BULK_FERMENT_MIN_MIN,
    PLAN_BULK_FERMENT_Q10,
    PLAN_BULK_FERMENT_REFERENCE_TEMP_C,
    PLAN_DEADLINE_TOLERANCE_MIN,
    PLAN_MIX_DURATION_MIN,
    PLAN_NORMAL_HOURS_END,
    PLAN_NORMAL_HOURS_START,
    PLAN_PREHEAT_DURATION_MIN,
    PLAN_PROOF_DURATION_MIN,
    PLAN_PROOF_MAX_MIN,
    PLAN_REST_DURATION_MIN,
    PLAN_ROOM_TEMP_PROOF_BASE_MIN,
    PLAN_ROOM_TEMP_PROOF_MAX_MIN,
    PLAN_ROOM_TEMP_PROOF_MIN_MIN,
    PLAN_SCORE_DURATION_MIN,
    PLAN_SF_ACTIVE_MIN,
    PLAN_SF_COUNT,
    PLAN_SF_INTERVAL_MIN,
    PLAN_SHAPING_DURATION_MIN,
    PLAN_WARM_WATER_TEMP_C,
)

_MELBOURNE_TZ = ZoneInfo("Australia/Melbourne")
_NOW_TOLERANCE_S = 2 * 3600  # seconds — within this window "right now" skips 8am clamp

# Variants tried in order when optimising for deadline.
# Each is a dict of keyword args for _build_steps (excluding state and deadline).
_VARIANTS: list[dict] = [
    {},
    {"skip_bench_rest": True},
    {"room_temp_proof": True},
    {"room_temp_proof": True, "skip_bench_rest": True},
    {"warm_water_bulk": True},
    {"warm_water_bulk": True, "skip_bench_rest": True},
    {"warm_water_bulk": True, "room_temp_proof": True},
    {"warm_water_bulk": True, "room_temp_proof": True, "skip_bench_rest": True},
]


# ---------------------------------------------------------------------------
# Duration calculators
# ---------------------------------------------------------------------------


def calc_bulk_ferment_duration(
    weather_weighted_temps: dict | None,
    effective_temp: float | None = None,
) -> int:
    """Return bulk fermentation duration in minutes via Q10.

    Pass effective_temp to override the ambient average (e.g. warm water trick).
    Falls back to config default when no weather data is available.
    """
    if effective_temp is not None:
        avg_temp = effective_temp
    else:
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


def calc_room_temp_proof_duration(weather_weighted_temps: dict | None) -> int:
    """Return room-temperature proof duration in minutes via Q10 (same ambient temps)."""
    temps = [
        v
        for k, v in (weather_weighted_temps or {}).items()
        if k in ("hour_0", "hour_2") and v is not None
    ]
    avg_temp = sum(temps) / len(temps) if temps else PLAN_BULK_FERMENT_REFERENCE_TEMP_C
    adjusted = PLAN_ROOM_TEMP_PROOF_BASE_MIN * (
        PLAN_BULK_FERMENT_Q10 ** ((PLAN_BULK_FERMENT_REFERENCE_TEMP_C - avg_temp) / 10)
    )
    return max(PLAN_ROOM_TEMP_PROOF_MIN_MIN, min(PLAN_ROOM_TEMP_PROOF_MAX_MIN, round(adjusted)))


# ---------------------------------------------------------------------------
# Datetime helpers
# ---------------------------------------------------------------------------


def _clamp_to_normal_hours(dt: datetime.datetime) -> datetime.datetime:
    """Shift dt to 8am if it falls before 8am or at/after 10pm.

    Exception: if dt is within 2 hours of the current Melbourne time, the user
    is starting right now — honour any pre-8am start.  The 10pm curfew still applies.
    """
    if dt.hour >= PLAN_NORMAL_HOURS_END:
        return (dt + datetime.timedelta(days=1)).replace(
            hour=PLAN_NORMAL_HOURS_START, minute=0, second=0, microsecond=0
        )
    if dt.hour < PLAN_NORMAL_HOURS_START:
        now_mel = datetime.datetime.now(_MELBOURNE_TZ).replace(tzinfo=None)
        if abs((dt - now_mel).total_seconds()) <= _NOW_TOLERANCE_S:
            return dt
        return dt.replace(hour=PLAN_NORMAL_HOURS_START, minute=0, second=0, microsecond=0)
    return dt


def _combine_local(d: datetime.date, hour: int, ref: datetime.datetime) -> datetime.datetime:
    t = datetime.time(hour, 0)
    if ref.tzinfo is not None:
        return datetime.datetime.combine(d, t, tzinfo=ref.tzinfo)
    return datetime.datetime.combine(d, t)


def _parse_intake_dt(iso: str) -> datetime.datetime:
    """Parse an intake ISO string as naive Melbourne local time."""
    dt = datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return dt.replace(tzinfo=None)


def _round_to_nearest_5(dt: datetime.datetime) -> datetime.datetime:
    total_minutes = dt.hour * 60 + dt.minute
    rounded = round(total_minutes / 5) * 5
    return dt.replace(hour=rounded // 60, minute=rounded % 60, second=0, microsecond=0)


def _is_waking_hours(dt: datetime.datetime) -> bool:
    """True if dt falls within waking hours (8am ≤ hour < 10pm)."""
    return PLAN_NORMAL_HOURS_START <= dt.hour < PLAN_NORMAL_HOURS_END


def _parse_conflict_dt(iso: str) -> datetime.datetime:
    """Parse a conflict ISO string as naive local time."""
    dt = datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return dt.replace(tzinfo=None)


def _clashes(step: dict, conflicts: list[dict]) -> bool:
    """True if the step's window overlaps any conflict window."""
    step_start = datetime.datetime.fromisoformat(step["start_iso"])
    # Treat zero-duration steps as 1 min so point-in-time steps can still clash.
    step_end = step_start + datetime.timedelta(minutes=max(step["duration_min"], 1))
    for c in conflicts:
        c_start = _parse_conflict_dt(c["from_iso"])
        c_end = _parse_conflict_dt(c["to_iso"])
        if step_start < c_end and step_end > c_start:
            return True
    return False


# ---------------------------------------------------------------------------
# Proof / baking-start helpers
# ---------------------------------------------------------------------------


def _find_baking_start(proof_start: datetime.datetime, post_proof_min: int) -> datetime.datetime:
    """Earliest valid cold-proof baking start (waking hours, proof 12–48h)."""
    min_end = proof_start + datetime.timedelta(minutes=PLAN_PROOF_DURATION_MIN)
    max_end = proof_start + datetime.timedelta(minutes=PLAN_PROOF_MAX_MIN)

    check_date = min_end.date()
    for _ in range(4):
        day_start = _combine_local(check_date, PLAN_NORMAL_HOURS_START, proof_start)
        day_end = _combine_local(check_date, PLAN_NORMAL_HOURS_END, proof_start)

        candidate = max(day_start, min_end)
        if candidate > max_end:
            break
        if candidate + datetime.timedelta(minutes=post_proof_min) <= day_end:
            return candidate

        check_date += datetime.timedelta(days=1)

    return min_end


def _best_baking_start(
    proof_start: datetime.datetime,
    post_proof_min: int,
    deadline: datetime.datetime,
) -> datetime.datetime:
    """Valid cold-proof baking start that makes Enjoy! land closest to deadline."""
    ideal = deadline - datetime.timedelta(minutes=post_proof_min)
    min_end = proof_start + datetime.timedelta(minutes=PLAN_PROOF_DURATION_MIN)
    max_end = proof_start + datetime.timedelta(minutes=PLAN_PROOF_MAX_MIN)

    best: datetime.datetime | None = None
    best_dist = float("inf")

    check_date = min_end.date()
    for _ in range(4):
        day_start = _combine_local(check_date, PLAN_NORMAL_HOURS_START, proof_start)
        day_end = _combine_local(check_date, PLAN_NORMAL_HOURS_END, proof_start)

        window_lo = max(day_start, min_end)
        window_hi = min(day_end - datetime.timedelta(minutes=post_proof_min), max_end)

        if window_lo <= window_hi:
            candidate = max(window_lo, min(window_hi, ideal))
            dist = abs((candidate - ideal).total_seconds())
            if dist < best_dist:
                best_dist = dist
                best = candidate

        check_date += datetime.timedelta(days=1)

    return best or min_end


# ---------------------------------------------------------------------------
# Core schedule builder
# ---------------------------------------------------------------------------


def _build_steps(
    state,
    *,
    skip_bench_rest: bool = False,
    warm_water_bulk: bool = False,
    room_temp_proof: bool = False,
    deadline: datetime.datetime | None = None,
    conflicts: list[dict] | None = None,
) -> tuple[list[dict], list[str]] | None:
    """Build a schedule variant.

    Returns (steps, skipped_step_ids) or None if the variant is infeasible.

    Active steps that clash with a conflict window are handled as follows:
    - skippable steps (sf_1–sf_4): silently dropped, their IDs collected in skipped_step_ids
    - non-skippable steps: variant is infeasible → return None
    Passive steps are never checked for clashes.
    """
    conflicts = conflicts or []
    start_iso = state.intake["earliest_start_time"]
    cursor = _parse_intake_dt(start_iso)
    cursor = _clamp_to_normal_hours(cursor)
    cursor = _round_to_nearest_5(cursor)

    temps = state.weather_weighted_temps
    bulk_min = calc_bulk_ferment_duration(
        temps,
        effective_temp=PLAN_WARM_WATER_TEMP_C if warm_water_bulk else None,
    )

    post_proof_min = (
        PLAN_PREHEAT_DURATION_MIN
        + PLAN_SCORE_DURATION_MIN
        + PLAN_BAKE_LID_ON_MIN
        + PLAN_BAKE_LID_OFF_MIN
        + PLAN_REST_DURATION_MIN
    )

    steps: list[dict] = []
    skipped: list[str] = []

    # Big mix (active, not skippable)
    big_mix = {
        "step_id": "big_mix",
        "label": "The big mix",
        "start_iso": cursor.isoformat(),
        "duration_min": PLAN_MIX_DURATION_MIN,
        "substep": False,
        "active": True,
        "skippable": False,
    }
    if conflicts and _clashes(big_mix, conflicts):
        return None
    steps.append(big_mix)
    cursor += datetime.timedelta(minutes=PLAN_MIX_DURATION_MIN)

    # Bulk fermentation (passive, not skippable)
    bulk_start = cursor
    steps.append(
        {
            "step_id": "bulk_ferment",
            "label": "Bulk fermentation",
            "start_iso": cursor.isoformat(),
            "duration_min": bulk_min,
            "substep": False,
            "active": False,
            "skippable": False,
        }
    )

    # Stretch & fold sub-steps (active, skippable)
    sf_cursor = bulk_start + datetime.timedelta(minutes=PLAN_SF_INTERVAL_MIN)
    for i in range(1, PLAN_SF_COUNT + 1):
        sf_step = {
            "step_id": f"sf_{i}",
            "label": f"Stretch & fold set {i}",
            "start_iso": sf_cursor.isoformat(),
            "duration_min": PLAN_SF_ACTIVE_MIN,
            "substep": True,
            "active": True,
            "skippable": True,
        }
        if not _is_waking_hours(sf_cursor) or (conflicts and _clashes(sf_step, conflicts)):
            skipped.append(f"sf_{i}")
        else:
            steps.append(sf_step)
        sf_cursor += datetime.timedelta(minutes=PLAN_SF_INTERVAL_MIN)

    cursor += datetime.timedelta(minutes=bulk_min)

    # Guard: shaping must land within waking hours — long bulk ferments can push it to 2am.
    if not _is_waking_hours(cursor):
        return None

    # Shaping (active, not skippable)
    shaping = {
        "step_id": "shaping",
        "label": "Shaping",
        "start_iso": cursor.isoformat(),
        "duration_min": PLAN_SHAPING_DURATION_MIN,
        "substep": False,
        "active": True,
        "skippable": False,
    }
    if conflicts and _clashes(shaping, conflicts):
        return None
    steps.append(shaping)
    cursor += datetime.timedelta(minutes=PLAN_SHAPING_DURATION_MIN)

    # Bench rest (passive, skippable — variant flag or future conflict logic)
    if not skip_bench_rest:
        steps.append(
            {
                "step_id": "bench_rest",
                "label": "Bench rest",
                "start_iso": cursor.isoformat(),
                "duration_min": PLAN_BENCH_REST_DURATION_MIN,
                "substep": False,
                "active": False,
                "skippable": True,
            }
        )
        cursor += datetime.timedelta(minutes=PLAN_BENCH_REST_DURATION_MIN)

    # Proof
    proof_start = cursor

    if room_temp_proof:
        proof_min = calc_room_temp_proof_duration(temps)
        baking_start = proof_start + datetime.timedelta(minutes=proof_min)
        day_start_8 = _combine_local(baking_start.date(), PLAN_NORMAL_HOURS_START, proof_start)
        day_end_10 = _combine_local(baking_start.date(), PLAN_NORMAL_HOURS_END, proof_start)
        if (
            baking_start < day_start_8
            or baking_start + datetime.timedelta(minutes=post_proof_min) > day_end_10
        ):
            return None  # baking would fall outside waking hours
        proof_label = "Proof (room temp)"
    else:
        baking_start = (
            _best_baking_start(proof_start, post_proof_min, deadline)
            if deadline is not None
            else _find_baking_start(proof_start, post_proof_min)
        )
        proof_min = int((baking_start - proof_start).total_seconds() / 60)
        proof_label = "Proof (cold)"

    steps.append(
        {
            "step_id": "proof",
            "label": proof_label,
            "start_iso": proof_start.isoformat(),
            "duration_min": proof_min,
            "substep": False,
            "active": False,
            "skippable": False,
        }
    )
    cursor = baking_start

    # Post-proof steps
    for step_id, label, duration, is_active in [
        ("preheat", "Preheat oven", PLAN_PREHEAT_DURATION_MIN, True),
        ("score", "Score", PLAN_SCORE_DURATION_MIN, True),
        ("bake_lid_on", "Bake (lid on)", PLAN_BAKE_LID_ON_MIN, True),
        ("bake_lid_off", "Bake (lid off)", PLAN_BAKE_LID_OFF_MIN, True),
        ("rest", "Rest", PLAN_REST_DURATION_MIN, False),
    ]:
        step = {
            "step_id": step_id,
            "label": label,
            "start_iso": cursor.isoformat(),
            "duration_min": duration,
            "substep": False,
            "active": is_active,
            "skippable": False,
        }
        if conflicts and is_active and _clashes(step, conflicts):
            return None
        steps.append(step)
        cursor += datetime.timedelta(minutes=duration)

    steps.append(
        {
            "step_id": "enjoy",
            "label": "Enjoy!",
            "start_iso": cursor.isoformat(),
            "duration_min": 0,
            "substep": False,
            "active": False,
            "skippable": False,
        }
    )

    return steps, skipped


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def build_schedule(state) -> list[dict]:
    """Natural schedule without deadline optimisation."""
    result = _build_steps(state)
    return result[0] if result else []


def build_optimized_schedule(
    state, conflicts: list[dict] | None = None
) -> tuple[list[dict], list[str], dict, list[str]]:
    """Build the schedule variant that lands Enjoy! closest to the deadline.

    Returns (schedule, notes, best_variant, skipped_step_ids).
    """
    conflicts = conflicts or []
    deadline_iso = state.intake.get("deadline")
    if not deadline_iso:
        result = _build_steps(state, conflicts=conflicts)
        if result is None:
            return [], [], {}, []
        schedule, skipped = result
        return schedule, _build_notes(schedule, {}, None, None), {}, skipped

    deadline = _parse_intake_dt(deadline_iso)

    def enjoy_dt(sched: list[dict]) -> datetime.datetime:
        s = next(s for s in sched if s["step_id"] == "enjoy")
        return datetime.datetime.fromisoformat(s["start_iso"])

    best_sched: list[dict] | None = None
    best_skipped: list[str] = []
    best_dist = float("inf")
    best_variant: dict = {}

    for variant in _VARIANTS:
        result = _build_steps(state, deadline=deadline, conflicts=conflicts, **variant)
        if result is None:
            continue
        sched, skipped = result
        dist = abs((enjoy_dt(sched) - deadline).total_seconds())
        if dist < best_dist:
            best_dist = dist
            best_sched = sched
            best_skipped = skipped
            best_variant = variant
        if dist <= PLAN_DEADLINE_TOLERANCE_MIN * 60:
            break

    # Deadline-far case: all variants land too early even at max proof → delay the start.
    if best_sched is not None and enjoy_dt(best_sched) < deadline - datetime.timedelta(
        minutes=PLAN_DEADLINE_TOLERANCE_MIN
    ):
        bulk_min = calc_bulk_ferment_duration(state.weather_weighted_temps)
        pre_proof_min = (
            PLAN_MIX_DURATION_MIN
            + bulk_min
            + PLAN_SHAPING_DURATION_MIN
            + PLAN_BENCH_REST_DURATION_MIN
        )
        _post_proof_min = (
            PLAN_PREHEAT_DURATION_MIN
            + PLAN_SCORE_DURATION_MIN
            + PLAN_BAKE_LID_ON_MIN
            + PLAN_BAKE_LID_OFF_MIN
            + PLAN_REST_DURATION_MIN
        )
        delayed_start = deadline - datetime.timedelta(
            minutes=_post_proof_min + PLAN_PROOF_MAX_MIN + pre_proof_min
        )
        delayed_start = _clamp_to_normal_hours(delayed_start)
        delayed_start = _round_to_nearest_5(delayed_start)
        adj_state = copy.copy(state)
        adj_state.intake = {**state.intake, "earliest_start_time": delayed_start.isoformat()}
        result = _build_steps(adj_state, deadline=deadline, conflicts=conflicts)
        if result is not None:
            delayed_sched, delayed_skipped = result
            dist = abs((enjoy_dt(delayed_sched) - deadline).total_seconds())
            if dist < best_dist:
                best_sched = delayed_sched
                best_skipped = delayed_skipped
                best_variant = {}

    if best_sched is None:
        # All conflict-aware variants failed — fall back to unconstrained schedule so the
        # commit stage can show the plan and flag remaining hard clashes to the user.
        result = _build_steps(state)
        if result is not None:
            best_sched, best_skipped = result
        else:
            best_sched = []
            best_skipped = []
        best_variant = {}

    return (
        best_sched,
        _build_notes(best_sched, best_variant, deadline, enjoy_dt(best_sched))
        if best_sched
        else [],
        best_variant,
        best_skipped,
    )


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------


def _build_notes(
    schedule: list[dict],
    variant: dict,
    deadline: datetime.datetime | None,
    enjoy: datetime.datetime | None,
) -> list[str]:
    notes: list[str] = []

    bulk = next((s for s in schedule if s["step_id"] == "bulk_ferment"), None)
    if bulk and bulk["duration_min"] != PLAN_BULK_FERMENT_DURATION_MIN:
        if variant.get("warm_water_bulk"):
            notes.append(
                f"Bulk fermentation accelerated to {_fmt_duration(bulk['duration_min'])} "
                f"(usual {_fmt_duration(PLAN_BULK_FERMENT_DURATION_MIN)}) "
                "using the warm water technique."
            )
        else:
            direction = (
                "extended" if bulk["duration_min"] > PLAN_BULK_FERMENT_DURATION_MIN else "shortened"
            )
            notes.append(
                f"Bulk fermentation {direction} to "
                f"{_fmt_duration(bulk['duration_min'])} "
                f"(usual {_fmt_duration(PLAN_BULK_FERMENT_DURATION_MIN)}) "
                "based on Melbourne's temperature forecast."
            )

    proof = next((s for s in schedule if s["step_id"] == "proof"), None)
    preheat = next((s for s in schedule if s["step_id"] == "preheat"), None)
    if variant.get("room_temp_proof") and proof:
        notes.append(
            f"Room temperature proof ({_fmt_duration(proof['duration_min'])}) "
            "used to meet your deadline."
        )
    elif proof and proof["duration_min"] > PLAN_PROOF_DURATION_MIN and preheat:
        notes.append(
            f"Cold proof extended to {_fmt_duration(proof['duration_min'])} "
            f"(minimum {_fmt_duration(PLAN_PROOF_DURATION_MIN)}) "
            f"to schedule baking from {_fmt_time(preheat['start_iso'])}."
        )

    if variant.get("skip_bench_rest"):
        notes.append("Bench rest skipped to better meet your deadline.")

    if deadline is not None and enjoy is not None:
        delta_s = (enjoy - deadline).total_seconds()
        if abs(delta_s) > PLAN_DEADLINE_TOLERANCE_MIN * 60:
            delta_min = int(abs(delta_s) / 60)
            direction = "after" if delta_s > 0 else "before"
            notes.append(
                f"⚠️ Closest match — Enjoy! lands {delta_min} min {direction} your deadline."
            )

    return notes


def build_schedule_notes(schedule: list[dict]) -> list[str]:
    """Notes for a schedule built without deadline optimisation."""
    return _build_notes(schedule, {}, None, None)


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def _fmt_duration(minutes: int) -> str:
    if minutes == 0:
        return "—"
    if minutes < 60:
        return f"{minutes} min"
    h, m = divmod(minutes, 60)
    return f"{h}h {m}m" if m else f"{h}h"


def _fmt_time(iso: str) -> str:
    return datetime.datetime.fromisoformat(iso).strftime("%a %H:%M")


def format_schedule(schedule: list[dict]) -> str:
    """Return a fixed-width plain-text table suitable for a Telegram code block."""
    col_step = 24
    col_start = 10
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
