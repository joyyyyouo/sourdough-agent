from config import (
    PLAN_BULK_FERMENT_DURATION_MIN,
    PLAN_BULK_FERMENT_MAX_MIN,
    PLAN_BULK_FERMENT_MIN_MIN,
)
from engine.stages.plan import calc_bulk_ferment_duration


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
