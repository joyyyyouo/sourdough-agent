# Couch to Crust

A conversational AI agent that builds a personalised sourdough baking schedule around your starter, your availability, and Melbourne's live weather forecast. Because sourdough is a 12+ hour process with a lot of moving parts.

## What it does

1. **Readiness check** — learns your experience level and confirms you have the gear
2. **Intake** — collects starter health, last feeding time, feeding ratio, your deadline, and the earliest you can start
3. **Weather fetch** — pulls Melbourne's hourly forecast and samples temperature at hour 0, 2, and 5 of your bake window (fermentation speed is highly temperature-sensitive)
4. **Scheduling** — builds an hour-by-hour baking plan from your starter data, deadline, and weather, trying up to 8 schedule variants (skip bench rest, warm water bulk, room-temperature proof, and combinations) to land *Enjoy!* within 30 minutes of your deadline; automatically delays the start when the deadline is far in the future
5. **Commitment** *(coming soon)* — presents the plan, lets you flag conflicts, and revises until you're happy
6. **Bake monitoring** *(coming soon)* — walks you through each step, checks you in, and adapts if something goes sideways

Sessions persist across restarts — your conversation state is saved to SQLite and restored from your Telegram chat ID.

## Stack

- **UI** — [Telegram bot](https://core.telegram.org/bots) via [python-telegram-bot](https://python-telegram-bot.org)
- **Agent orchestration** — plain Python state machine (`engine/agent.py`)
- **LLM** — Google Gemini 2.5 Flash via [LangChain Google GenAI](https://python.langchain.com/docs/integrations/chat/google_generative_ai/)
- **Persistence** — SQLite (`data/sourdough.db`) for both structured bake data and agent checkpoints
- **Weather** — [Open-Meteo](https://open-meteo.com) (free, no API key required)

## Setup

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then:

```bash
uv sync
```

Copy `.env.example` to `.env` and fill in both values:

```
GOOGLE_API_KEY=...       # https://aistudio.google.com
TELEGRAM_BOT_TOKEN=...   # from @BotFather on Telegram
```

## Running

```bash
uv run python telegram_bot.py
```

Bot commands:
- `/start` — resume your session (or start a new one if none exists)
- `/reset` — wipe your session and start a completely fresh bake
- `/help` — show available commands

To manually refresh the weather forecast:

```bash
uv run python scraper.py
```

The scraper fetches 7 days of hourly Melbourne temperature and humidity from Open-Meteo and writes them to `data/sourdough.db`. The `fetch_weather` stage triggers this automatically if the last scrape is more than 12 hours old.

## Running tests

```bash
uv run pytest tests/ -v
```

## Project structure

```
telegram_bot.py     Telegram bot entry point and session management
service.py          BakingAgentService — boundary between UI and engine
scraper.py          CLI shim → delegates to engine/weather.py
config.py           DB path, model name, weather coordinates, env vars

engine/
  agent.py          State machine loop, stage transitions, LLM calls
  weather.py        Open-Meteo fetch, DB persistence, time-weighted temp calculation

  stages/
    readiness.py    Experience check + equipment checklist (SubmitReadiness tool)
    intake.py       Starter info, deadline, earliest start time (SubmitIntake tool)
    plan.py         Schedule builder, deadline optimisation, 8-variant search

infra/
  db.py             SQLite schema, migrations, and query helpers

tests/
  test_agent.py     State machine transitions, serialisation, tool dispatch
  test_weather.py   Time-weighted temperature calculation
```

## Stage machine

```
assess_readiness        ← implemented
    → collect_context   ← implemented
    → fetch_weather     ← implemented (auto-stage, no user input)
    → plan              ← implemented (auto-stage, no user input)
    → commit ←──────────────────────┐
         │                          │
    [conflicts]                     │
         → plan ────────────────────┘
    [confirmed]
         → guide
         → complete
```

## Session persistence

Each Telegram user is identified by their `chat_id`, used as the session key in `user_sessions`. The full `AgentState` is serialised to JSON and written to `agent_checkpoints` after every message, so state survives bot restarts. Use `/reset` to start a fresh session under the same Telegram account.

## Weather and fermentation

Bulk fermentation speed depends heavily on ambient temperature. The `fetch_weather` stage samples Melbourne's forecast at three points in the bake window:

| Checkpoint | Why |
|---|---|
| Hour 0 (start) | Sets the baseline for bulk ferment speed |
| Hour 2 | Captures any mid-morning temperature swing |
| Hour 5 | Reflects conditions during shaping / cold proof handoff |

These values are stored on the `bake_sessions` row (`weather_hour0/2/5_temp_c`) alongside the `scrape_run_id` so the schedule can be reproduced exactly given only the session record.

## Scheduling and deadline optimisation

The `plan` auto-stage builds a schedule from a fixed set of steps:

| Step | Duration |
|------|----------|
| The big mix | 15 min |
| Bulk fermentation + 4× stretch & fold | Q10-adjusted (2h–10h) |
| Shaping | 20 min |
| Bench rest | 20 min |
| Proof (cold) | 12h–48h |
| Preheat oven | 45 min |
| Score | 5 min |
| Bake (lid on / lid off) | 25 + 15 min |
| Rest | 60 min |

To hit your deadline, the planner tries 8 variants in order — skipping bench rest, using the warm water technique to accelerate bulk fermentation, switching to a room-temperature proof, and combinations of all three. It picks whichever variant lands *Enjoy!* closest to your deadline.

If all variants land too early (deadline is far in the future), the planner works backward from your deadline through the fixed step durations to compute a later start time, using the full 48-hour cold proof as a stretch buffer.

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
