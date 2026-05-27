import datetime

from config import (
    PLAN_BULK_FERMENT_DURATION_MIN,
    PLAN_BULK_FERMENT_MAX_MIN,
    PLAN_BULK_FERMENT_MIN_MIN,
    PLAN_DEADLINE_TOLERANCE_MIN,
    PLAN_NORMAL_HOURS_END,
    PLAN_NORMAL_HOURS_START,
)
from engine.agent import AgentState
from engine.stages.plan import build_optimized_schedule, calc_bulk_ferment_duration


class TestCalcBulkFermentDuration:
    def test_no_weather_data_returns_default(self):
        assert calc_bulk_ferment_duration(None) == PLAN_BULK_FERMENT_DURATION_MIN

    def test_empty_dict_returns_default(self):
        assert calc_bulk_ferment_duration({}) == PLAN_BULK_FERMENT_DURATION_MIN

    def test_all_none_temps_returns_default(self):
        temps = {"hour_0": None, "hour_2": None, "hour_5": None}
        assert calc_bulk_ferment_duration(temps) == PLAN_BULK_FERMENT_DURATION_MIN

    def test_reference_temp_returns_base(self):
        result = calc_bulk_ferment_duration({"hour_0": 24.0, "hour_2": 24.0})
        assert result == PLAN_BULK_FERMENT_DURATION_MIN

    def test_cooler_temp_increases_duration(self):
        result = calc_bulk_ferment_duration({"hour_0": 20.0, "hour_2": 20.0})
        assert 430 <= result <= 442  # ~436 min expected

    def test_warmer_temp_decreases_duration(self):
        result = calc_bulk_ferment_duration({"hour_0": 28.0, "hour_2": 28.0})
        assert 247 <= result <= 253  # ~250 min expected

    def test_ceiling_clamp_on_extreme_cold(self):
        # Very cold → very slow fermentation → hits 10h ceiling
        result = calc_bulk_ferment_duration({"hour_0": 0.0, "hour_2": 0.0})
        assert result == PLAN_BULK_FERMENT_MAX_MIN

    def test_floor_clamp_on_extreme_heat(self):
        # Very hot → very fast fermentation → hits 2h floor
        result = calc_bulk_ferment_duration({"hour_0": 50.0, "hour_2": 50.0})
        assert result == PLAN_BULK_FERMENT_MIN_MIN

    def test_only_hour_0_available(self):
        result = calc_bulk_ferment_duration({"hour_0": 20.0, "hour_2": None})
        assert 430 <= result <= 442

    def test_only_hour_2_available(self):
        result = calc_bulk_ferment_duration({"hour_0": None, "hour_2": 28.0})
        assert 247 <= result <= 253

    def test_hour_5_is_ignored(self):
        # hour_5 is outside the bulk fermentation window — should not affect result
        result = calc_bulk_ferment_duration({"hour_0": None, "hour_2": None, "hour_5": 10.0})
        assert result == PLAN_BULK_FERMENT_DURATION_MIN

    def test_averages_hour_0_and_hour_2(self):
        # 20°C and 28°C average to 24°C → should return base duration
        result = calc_bulk_ferment_duration({"hour_0": 20.0, "hour_2": 28.0})
        assert result == PLAN_BULK_FERMENT_DURATION_MIN


class TestBuildOptimizedSchedule:
    def _make_state(self, start_iso: str, deadline_iso: str) -> AgentState:
        state = AgentState()
        state.intake = {
            "earliest_start_time": start_iso,
            "deadline": deadline_iso,
            "starter_health": "active",
            "last_fed_at": start_iso,
            "feeding_ratio": "1:1:1",
        }
        state.weather_weighted_temps = {"hour_0": 24.0, "hour_2": 24.0}
        return state

    def test_distant_deadline_delays_start(self):
        # Deadline 4.5 days away — without the fix, Enjoy! would land ~4 days early.
        # With the fix, the schedule is rebuilt with a later start so Enjoy! is ≤30 min off.
        start = datetime.datetime(2026, 5, 27, 8, 0)  # Tuesday 8am
        deadline = datetime.datetime(2026, 6, 1, 20, 0)  # Sunday 8pm (~108h later)
        state = self._make_state(start.isoformat(), deadline.isoformat())
        schedule, _, _, _ = build_optimized_schedule(state)
        enjoy = next(s for s in schedule if s["step_id"] == "enjoy")
        enjoy_dt = datetime.datetime.fromisoformat(enjoy["start_iso"])
        diff_min = abs((enjoy_dt - deadline).total_seconds()) / 60
        assert diff_min <= PLAN_DEADLINE_TOLERANCE_MIN, (
            f"Enjoy! at {enjoy_dt} is {diff_min:.1f} min from deadline {deadline}; "
            f"expected within {PLAN_DEADLINE_TOLERANCE_MIN} min"
        )

    def test_all_steps_have_active_and_skippable_flags(self):
        start = datetime.datetime(2026, 5, 27, 8, 0)
        deadline = datetime.datetime(2026, 5, 28, 18, 0)
        state = self._make_state(start.isoformat(), deadline.isoformat())
        schedule, _, _, _ = build_optimized_schedule(state)
        assert schedule, "Schedule should not be empty"
        for step in schedule:
            assert "active" in step, f"Step {step['step_id']} missing 'active' field"
            assert "skippable" in step, f"Step {step['step_id']} missing 'skippable' field"

    def test_waking_hours_guard_rejects_late_shaping(self):
        # At 0°C bulk ferment hits MAX (10h); starting at 15:00 → shaping at ~01:15 (outside
        # waking hours). The guard should reject the default variant, forcing the optimizer
        # to pick warm_water_bulk which shortens bulk enough to keep shaping in the day.
        start = datetime.datetime(2026, 5, 27, 15, 0)
        deadline = datetime.datetime(2026, 5, 29, 12, 0)
        state = self._make_state(start.isoformat(), deadline.isoformat())
        state.weather_weighted_temps = {"hour_0": 0.0, "hour_2": 0.0}  # extreme cold

        schedule, _, _, _ = build_optimized_schedule(state)
        assert schedule, "Schedule should not be empty"
        shaping = next((s for s in schedule if s["step_id"] == "shaping"), None)
        assert shaping is not None
        shaping_dt = datetime.datetime.fromisoformat(shaping["start_iso"])
        assert PLAN_NORMAL_HOURS_START <= shaping_dt.hour < PLAN_NORMAL_HOURS_END, (
            f"Shaping at {shaping_dt} is outside waking hours"
        )

    def test_conflict_skips_sf_step(self):
        # sf_2 lands at bulk_start + 60 min = 08:15 + 60 = 09:15 (with 08:00 start, 15-min mix).
        # A conflict covering 09:10–09:25 should skip sf_2 but keep the rest.
        start = datetime.datetime(2026, 5, 27, 8, 0)
        deadline = datetime.datetime(2026, 5, 28, 18, 0)
        state = self._make_state(start.isoformat(), deadline.isoformat())

        conflict = [
            {
                "from_iso": "2026-05-27T09:10:00",
                "to_iso": "2026-05-27T09:25:00",
                "reason": "appointment",
            }
        ]
        schedule, _, _, skipped = build_optimized_schedule(state, conflicts=conflict)
        step_ids = [s["step_id"] for s in schedule]

        assert "sf_2" not in step_ids, "sf_2 should have been skipped due to conflict"
        assert "sf_2" in skipped
        assert "sf_1" in step_ids
        assert "sf_3" in step_ids
        assert "sf_4" in step_ids

    def test_hard_clash_falls_back_to_unconstrained_schedule(self):
        # Conflict window covers shaping (active, non-skippable) across all variants.
        # All conflict-aware variants return None; fallback produces an unconstrained schedule.
        start = datetime.datetime(2026, 5, 27, 8, 0)
        deadline = datetime.datetime(2026, 5, 28, 18, 0)
        state = self._make_state(start.isoformat(), deadline.isoformat())

        # Shaping happens after mix (15 min) + bulk (~6h at 24°C). Cover a wide window.
        conflict = [
            {"from_iso": "2026-05-27T14:00:00", "to_iso": "2026-05-28T08:00:00", "reason": "away"}
        ]
        schedule, _, _, _ = build_optimized_schedule(state, conflicts=conflict)
        # Should still return a non-empty schedule (the unconstrained fallback)
        assert schedule, "Expected a fallback schedule even when all conflict-aware variants fail"
        assert any(s["step_id"] == "enjoy" for s in schedule)

    def test_no_conflicts_returns_empty_skipped(self):
        start = datetime.datetime(2026, 5, 27, 8, 0)
        deadline = datetime.datetime(2026, 5, 28, 18, 0)
        state = self._make_state(start.isoformat(), deadline.isoformat())
        _, _, _, skipped = build_optimized_schedule(state)
        assert skipped == []

    def test_normal_start_includes_all_sf_sets(self):
        # With a mid-morning start and typical temps, all four S&F sets fall within waking
        # hours and must appear in the schedule (none skipped due to waking-hours check).
        start = datetime.datetime(2026, 5, 27, 8, 0)
        deadline = datetime.datetime(2026, 5, 28, 18, 0)
        state = self._make_state(start.isoformat(), deadline.isoformat())
        state.weather_weighted_temps = {"hour_0": 24.0, "hour_2": 24.0}

        schedule, _, _, skipped = build_optimized_schedule(state)
        step_ids = [s["step_id"] for s in schedule]

        for sf in ("sf_1", "sf_2", "sf_3", "sf_4"):
            assert sf in step_ids, f"{sf} should be in schedule (within waking hours)"
        assert not any(s.startswith("sf_") for s in skipped), "No S&F sets should be skipped"
