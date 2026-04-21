import datetime
import requests
from config import DB_PATH
from db import init_db, insert_scrape_run, insert_forecasts

API_URL = (
    "https://api.open-meteo.com/v1/forecast"
    "?latitude=-37.8136&longitude=144.9631"
    "&hourly=temperature_2m,relativehumidity_2m"
    "&timezone=UTC"
)


def fetch_forecast() -> list:
    resp = requests.get(API_URL, timeout=15)
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
    scraped_at = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    conn = init_db(DB_PATH)
    run_id = insert_scrape_run(conn, scraped_at)
    insert_forecasts(conn, run_id, rows)
    conn.close()

    print(f"Inserted {len(rows)} forecasts for run_id={run_id} (scraped_at={scraped_at})")


if __name__ == "__main__":
    main()
