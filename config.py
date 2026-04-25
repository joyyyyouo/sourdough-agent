from pathlib import Path

_DATA = Path(__file__).parent / "data"

DB_PATH = _DATA / "sourdough.db"

ASSISTANT_NAMES_PATH = _DATA / "assistant_names.txt"
ADJECTIVES_PATH = _DATA / "adjectives.txt"
LLM_MODEL = "gemini-2.5-flash"
LLM_TEMPERATURE = 1.4
LLM_TOP_P = 0.95

WEATHER_LAT = -37.8136  # Melbourne
WEATHER_LNG = 144.9631
WEATHER_TIMEOUT = 15  # scrape timeout
WEATHER_DATA_STALE_THRESHOLD_S = 12 * 3600  # re-scrape if latest run is older than this

# Default durations
{
    "autolyse_time_hours": 0.5,
    "bulk_fermentation_time_hours": 5.5,
    "bench_rest_time_hours": 0.33,
    "final_proof_time_hours": {
        "room_temp": 2.5,
        "cold_retard": 12,
    },
}
