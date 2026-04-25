"""Tests for engine.weather.get_time_weighted_temps.

These tests use an in-memory SQLite DB seeded with known forecast rows so that
the weighted-temp calculation can be reproduced given only a scrape_run_id.
"""


import pytest

from engine.weather import get_time_weighted_temps
from infra.db import init_db, insert_forecasts, insert_scrape_run

START_ISO = "2026-04-25T08:00:00Z"

# Known forecast data centred around 08:00 UTC on 2026-04-25.
# Open-Meteo returns times without Z; we match that format here.
_FORECAST_ROWS = [
    {"forecast_time": "2026-04-25T05:00", "temperature_c": 12.0, "humidity_pct": 70},
    {"forecast_time": "2026-04-25T06:00", "temperature_c": 13.0, "humidity_pct": 68},
    {"forecast_time": "2026-04-25T07:00", "temperature_c": 14.5, "humidity_pct": 65},
    {"forecast_time": "2026-04-25T08:00", "temperature_c": 16.0, "humidity_pct": 60},  # hour 0
    {"forecast_time": "2026-04-25T09:00", "temperature_c": 17.5, "humidity_pct": 58},
    {"forecast_time": "2026-04-25T10:00", "temperature_c": 19.0, "humidity_pct": 55},  # hour 2
    {"forecast_time": "2026-04-25T11:00", "temperature_c": 20.5, "humidity_pct": 52},
    {"forecast_time": "2026-04-25T12:00", "temperature_c": 21.0, "humidity_pct": 50},
    {"forecast_time": "2026-04-25T13:00", "temperature_c": 21.5, "humidity_pct": 48},  # hour 5
    {"forecast_time": "2026-04-25T14:00", "temperature_c": 22.0, "humidity_pct": 47},
]


@pytest.fixture
def seeded_db():
    """:memory: DB with one scrape_run and known forecast rows."""
    conn = init_db(":memory:")
    run_id = insert_scrape_run(conn, "2026-04-25T07:00:00Z")
    insert_forecasts(conn, run_id, _FORECAST_ROWS)
    return conn, run_id


def test_exact_hour_match(seeded_db):
    """Hour 0/2/5 align exactly with forecast rows — should return exact temps."""
    conn, run_id = seeded_db
    result = get_time_weighted_temps(conn, run_id, START_ISO)
    assert result["hour_0"] == 16.0  # 08:00
    assert result["hour_2"] == 19.0  # 10:00
    assert result["hour_5"] == 21.5  # 13:00


def test_closest_row_within_tolerance(seeded_db):
    """Start at :30 — targets land at 08:30, 10:30, 13:30.
    Nearest rows are 08:00 (30 min away), 10:00 (30 min away), 13:00 (30 min away).
    All are exactly on the ±30 min boundary — should still resolve."""
    conn, run_id = seeded_db
    result = get_time_weighted_temps(conn, run_id, "2026-04-25T08:30:00Z")
    # 08:30 → closest is 08:00 (delta=30 min) or 09:00 (delta=30 min); both equal.
    # The function picks whichever comes first in iteration order. Either is valid.
    assert result["hour_0"] in (16.0, 17.5)
    assert result["hour_2"] in (19.0, 20.5)  # 10:30 → 10:00 or 11:00
    assert result["hour_5"] in (21.5, 22.0)  # 13:30 → 13:00 or 14:00


def test_no_data_returns_none(seeded_db):
    """Start time far outside all forecast rows — all offsets should return None."""
    conn, run_id = seeded_db
    result = get_time_weighted_temps(conn, run_id, "2026-04-26T08:00:00Z")
    assert result["hour_0"] is None
    assert result["hour_2"] is None
    assert result["hour_5"] is None


def test_partial_coverage(seeded_db):
    """Hour 0 has data but hour 5 falls outside coverage — hour_5 returns None."""
    conn, run_id = seeded_db
    # Start at 11:00 — hour 5 target is 16:00, which has no forecast row.
    result = get_time_weighted_temps(conn, run_id, "2026-04-25T11:00:00Z")
    assert result["hour_0"] == 20.5  # 11:00 exact
    assert result["hour_2"] == 21.5  # 13:00 exact
    assert result["hour_5"] is None  # 16:00 — no row within ±30 min
