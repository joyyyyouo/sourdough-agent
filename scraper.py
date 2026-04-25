import datetime

import requests

from config import DB_PATH, WEATHER_LAT, WEATHER_LNG, WEATHER_TIMEOUT
from infra.db import init_db, insert_forecasts, insert_scrape_run

API_URL = (
    "https://api.open-meteo.com/v1/forecast"
    f"?latitude={WEATHER_LAT}&longitude={WEATHER_LNG}"
    "&hourly=temperature_2m,relativehumidity_2m"
    "&timezone=UTC"
)


def fetch_forecast() -> list[dict]:
    resp = requests.get(API_URL, timeout=WEATHER_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()["hourly"]
    return [
        {
            "forecast_time": t,
            "temperature_c": temp,
            "humidity_pct": hum,
        }
        for t, temp, hum in zip(
            data["time"],
            data["temperature_2m"],
            data["relativehumidity_2m"],
        )
    ]


def main():
    rows = fetch_forecast()
    scraped_at = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    conn = init_db(DB_PATH)
    run_id = insert_scrape_run(conn, scraped_at)
    insert_forecasts(conn, run_id, rows)
    conn.close()

    print(f"Inserted {len(rows)} forecasts for run_id={run_id} (scraped_at={scraped_at})")


if __name__ == "__main__":
    main()
