# Sourdough Baking Assistant

A conversational AI agent that builds a personalised sourdough baking schedule around your starter, your availability, and Melbourne's live weather forecast. Because sourdough is a 12+ hour process with a lot of moving parts.

## What it does

1. **Readiness check** — learns your experience level and confirms you have the gear
2. **Intake** — asks about your starter's health, when you last fed it, your feeding ratio, and when you want the loaf ready
3. **Scheduling** *(coming soon)* — generates an hour-by-hour baking plan using your starter data and live Melbourne weather
4. **Commitment** *(coming soon)* — presents the plan, lets you flag conflicts, and revises until you're happy
5. **Bake monitoring** *(coming soon)* — walks you through each step, checks you in, and adapts if something goes sideways (dough too wet? weather changed? running late?)

Sessions persist across browser closes — bookmark your URL and pick up exactly where you left off.

## Stack

- **UI** — [Streamlit](https://streamlit.io)
- **Agent orchestration** — [LangGraph](https://github.com/langchain-ai/langgraph)
- **LLM** — Google Gemini 2.5 Flash via [LangChain Google GenAI](https://python.langchain.com/docs/integrations/chat/google_generative_ai/)
- **Persistence** — SQLite (`sourdough.db`) for both structured bake data and LangGraph checkpoints
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

To refresh the weather forecast data:

```bash
uv run python scraper.py
```

This can be run as a cron job to keep forecasts current during a long bake.

## Project structure

```
app.py          Streamlit UI and session management
graph.py        LangGraph StateGraph — nodes and edges
state.py        AgentState schema
config.py       DB path and model name
db.py           SQLite schema and helpers
scraper.py      Open-Meteo weather fetcher

nodes/
  assess_readiness.py   Experience check + kit check
  intake.py             Starter info and deadline collection
  scheduler.py          Schedule generation (stub)
  commitment.py         Schedule review loop (stub)
  revision.py           Schedule revision (stub)
  bake_monitor.py       Step-by-step bake check-in (stub)
  diagnostic.py         Mid-bake issue diagnosis (stub)
```

## Graph topology

```
assess_readiness
    → intake
    → scheduler
    → commitment ←─────────────────────┐
         │                             │
    [conflicts]                        │
         → revision ───────────────────┘
    [confirmed]
         → bake_monitor
              │
         [issue reported]
              → diagnostic → revision
         [all steps done]
              → END
```

## Session persistence

Each browser session is assigned a `session_key` stored in the URL (`?s=<uuid>`). LangGraph checkpoints are written to `sourdough.db` via `SqliteSaver`, so the full conversation state — message history, bake data, completed steps — survives app restarts. The `user_sessions` table links the session key to the LangGraph thread ID and the bake record.

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
