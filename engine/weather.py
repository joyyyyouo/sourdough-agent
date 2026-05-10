import datetime
import sqlite3

import requests

from config import DB_PATH, WEATHER_LAT, WEATHER_LNG, WEATHER_TIMEOUT
from infra.db import (
    get_forecasts_for_run,
    init_db,
    insert_forecasts,
    insert_scrape_run,
)

API_URL = (
    "https://api.open-meteo.com/v1/forecast"
    f"?latitude={WEATHER_LAT}&longitude={WEATHER_LNG}"
    "&hourly=temperature_2m,relativehumidity_2m"
    "&timezone=UTC"
)

_OFFSETS_H = {"hour_0": 0, "hour_2": 2, "hour_5": 5}
_TOLERANCE_S = 30 * 60  # ±30 min — forecasts are hourly so this always matches on-the-hour


def fetch_forecast() -> list[dict]:
    """Hit Open-Meteo, return [{forecast_time, temperature_c, humidity_pct}, ...]."""
    resp = requests.get(API_URL, timeout=WEATHER_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()["hourly"]
    return [
        {"forecast_time": t, "temperature_c": temp, "humidity_pct": hum}
        for t, temp, hum in zip(data["time"], data["temperature_2m"], data["relativehumidity_2m"])
    ]


def fetch_and_save(conn: sqlite3.Connection, scraped_at: str) -> int:
    """Fetch from Open-Meteo API, write scrape_run + forecasts to DB, return run_id."""
    rows = fetch_forecast()
    run_id = insert_scrape_run(conn, scraped_at)
    insert_forecasts(conn, run_id, rows)
    return run_id


def get_time_weighted_temps(
    conn: sqlite3.Connection,
    scrape_run_id: int,
    start_iso: str,
) -> dict[str, float | None]:
    """Return temperatures at hour 0, 2, 5 from start_iso using the given scrape run.

    For each offset, picks the closest forecast row within ±30 min.
    Returns {"hour_0": float|None, "hour_2": float|None, "hour_5": float|None}.
    None means no forecast row fell within tolerance for that offset.
    """
    start_dt = _parse_iso(start_iso)
    rows = get_forecasts_for_run(conn, scrape_run_id)

    result: dict[str, float | None] = {}
    for key, offset_h in _OFFSETS_H.items():
        target_dt = start_dt + datetime.timedelta(hours=offset_h)
        best_temp: float | None = None
        best_delta: float | None = None
        for row in rows:
            ft = _parse_iso(row["forecast_time"])
            delta = abs((ft - target_dt).total_seconds())
            if delta <= _TOLERANCE_S and (best_delta is None or delta < best_delta):
                best_temp = row["temperature_c"]
                best_delta = delta
        result[key] = best_temp

    return result


def _parse_iso(s: str) -> datetime.datetime:
    """Parse ISO-8601 string, treating naive datetimes as UTC."""
    dt = datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt


def main() -> None:
    """CLI entry point — fetch fresh forecast and save to DB."""
    scraped_at = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = init_db(DB_PATH)
    rows = fetch_forecast()
    run_id = insert_scrape_run(conn, scraped_at)
    insert_forecasts(conn, run_id, rows)
    conn.close()
    print(f"Inserted {len(rows)} forecasts for run_id={run_id} (scraped_at={scraped_at})")
