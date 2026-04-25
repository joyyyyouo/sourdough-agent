# Couch to Crust

A conversational AI agent that builds a personalised sourdough baking schedule around your starter, your availability, and Melbourne's live weather forecast. Because sourdough is a 12+ hour process with a lot of moving parts.

## What it does

1. **Readiness check** — learns your experience level and confirms you have the gear
2. **Intake** — collects starter health, last feeding time, feeding ratio, your deadline, and the earliest you can start
3. **Weather fetch** — pulls Melbourne's hourly forecast and samples temperature at hour 0, 2, and 5 of your bake window (fermentation speed is highly temperature-sensitive)
4. **Scheduling** *(coming soon)* — generates an hour-by-hour baking plan from your starter data, deadline, and weather
5. **Commitment** *(coming soon)* — presents the plan, lets you flag conflicts, and revises until you're happy
6. **Bake monitoring** *(coming soon)* — walks you through each step, checks you in, and adapts if something goes sideways (dough too wet? weather changed? running late?)

Sessions persist across browser closes — bookmark your URL and pick up exactly where you left off.

## Stack

- **UI** — [Streamlit](https://streamlit.io)
- **Agent orchestration** — [LangGraph](https://github.com/langchain-ai/langgraph)
- **LLM** — Google Gemini 2.5 Flash via [LangChain Google GenAI](https://python.langchain.com/docs/integrations/chat/google_generative_ai/)
- **Persistence** — SQLite (`data/sourdough.db`) for both structured bake data and LangGraph checkpoints
- **Weather** — [Open-Meteo](https://open-meteo.com) (free, no API key required)

## Setup

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then:

```bash
uv sync
```

You'll need a Google API key with the Gemini API enabled. Get one at [aistudio.google.com](https://aistudio.google.com).

## Running

```bash
uv run streamlit run app.py
```

Enter your Google API key in the sidebar. Your session URL will look like `http://localhost:8501/?s=<uuid>` — bookmark it to return to your bake later.

To manually refresh the weather forecast data:

```bash
uv run python scraper.py
```

The scraper fetches 7 days of hourly Melbourne temperature and humidity from Open-Meteo and writes them to `data/sourdough.db`. The `fetch_weather` graph node triggers this automatically if the last scrape is more than 12 hours old.

## Running tests

```bash
uv run pytest tests/ -v
```

## Project structure

```
app.py              Streamlit UI and session management
service.py          BakingAgentService — thin wrapper so UI has no LangGraph imports
scraper.py          CLI shim → delegates to engine/weather.py
state.py            AgentState schema and Node enum
config.py           DB path, model name, weather coordinates

engine/
  graph.py          LangGraph StateGraph — nodes and edges
  weather.py        Open-Meteo fetch, DB persistence, time-weighted temp calculation

  nodes/
    check_readiness.py      Experience check + equipment checklist
    collect_bake_context.py Starter info, deadline, earliest start time collection
    fetch_weather.py        Weather staleness check, re-scrape if needed, temp sampling
    estimate_timeline.py    Schedule generation (stub)
    check_commitment.py     Schedule review loop (stub)
    adjust_schedule.py      Schedule revision (stub)
    guide_bake.py           Step-by-step bake check-in (stub)
    diagnose_issue.py       Mid-bake issue diagnosis (stub)
    utils.py                Shared helpers (clean_history)

infra/
  db.py             SQLite schema, migrations, and query helpers

tests/
  test_weather.py   Pytest suite for time-weighted temperature calculation
```

## Graph topology

```
check_readiness
    → collect_bake_context
    → fetch_weather
    → estimate_timeline
    → check_commitment ←──────────────────────┐
           │                                  │
      [conflicts]                             │
           → adjust_schedule ─────────────────┘
      [confirmed]
           → guide_bake
                │
           [issue reported]
                → diagnose_issue → adjust_schedule
           [all steps done]
                → END
```

## Session persistence

Each browser session is assigned a `session_key` stored in the URL (`?s=<uuid>`). LangGraph checkpoints are written to `data/sourdough.db` via `SqliteSaver`, so the full conversation state — message history, bake data, completed steps — survives app restarts. The `user_sessions` table links the session key to the LangGraph thread ID and the bake record.

## Weather and fermentation

Bulk fermentation speed depends heavily on ambient temperature. The `fetch_weather` node samples Melbourne's forecast at three points in the bake window:

| Checkpoint | Why |
|---|---|
| Hour 0 (start) | Sets the baseline for bulk ferment speed |
| Hour 2 | Captures any mid-morning temperature swing |
| Hour 5 | Reflects conditions during shaping / cold proof handoff |

These values are stored on the `bake_sessions` row (`weather_hour0/2/5_temp_c`) alongside the `scrape_run_id` so the schedule can be reproduced exactly given only the session record.

## Gear checklist

Must-haves:
- Active sourdough starter
- Bread flour (at least 500g)
- Water and salt
- Kitchen scale
- Large mixing bowl
- Dutch oven or cast-iron pot with a lid

Nice to have:
- Banneton / proofing basket (a floured bowl works)
- Bench scraper
- Bread lame or sharp razor for scoring
