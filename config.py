import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

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

TELEGRAM_BOT_TOKEN: str | None = os.getenv("TELEGRAM_BOT_TOKEN")

# Bake schedule step durations
PLAN_MIX_DURATION_MIN = 15
PLAN_SF_COUNT = 4
PLAN_SF_INTERVAL_MIN = 30  # gap between S&F sets; also offset of first set from bulk start
PLAN_SF_ACTIVE_MIN = 5  # active time per S&F set
PLAN_BULK_FERMENT_DURATION_MIN = 330  # 5h 30m at reference temp (24°C)
PLAN_BULK_FERMENT_REFERENCE_TEMP_C = 24.0
PLAN_BULK_FERMENT_Q10 = 2.0  # fermentation rate doubles per 10°C — standard Q10 for yeast/LAB
PLAN_BULK_FERMENT_MIN_MIN = 120  # floor: 2h
PLAN_BULK_FERMENT_MAX_MIN = 600  # ceiling: 10h
PLAN_SHAPING_DURATION_MIN = 20
PLAN_BENCH_REST_DURATION_MIN = 20
PLAN_PROOF_DURATION_MIN = 720  # 12h cold proof
