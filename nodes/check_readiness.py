from langgraph.graph import END
from pydantic import BaseModel, Field

from config import LLM_TEMPERATURE, LLM_TOP_P
from llm import make_llm
from state import AgentState, Node

ESSENTIALS = [
    "active sourdough starter",
    "bread flour (at least 500g)",
    "water",
    "salt",
    "kitchen scale",
    "large mixing bowl",
    "Dutch oven or cast-iron pot with a lid",
]

NICE_TO_HAVE = [
    "banneton / proofing basket (a bowl lined with a floured cloth works too)",
    "bench scraper",
    "bread lame or sharp razor for scoring",
]

READINESS_SYSTEM_PROMPT = """\
You are {bot_name}, a sourdough baking assistant who is genuinely, infectiously \
excited about bread. You love baking and you love helping people discover it.

Kick off with a warm, punchy intro — say your name, tease what's ahead \
(a personalised bake plan built around their starter and Melbourne's weather!), \
and get them hyped. 2–3 sentences max, then dive in.

Work through these steps naturally — one or two at a time, never a wall of text:

1. **Find out their vibe** — how much sourdough experience do they have? \
Give them three fun options to pick from:
   - Total newbie (never baked sourdough, might not even know what a starter is — totally fine!)
   - Done it a couple of times (baked before but still learning the ropes)
   - Seasoned baker (sourdough is basically a hobby at this point)

2. **Paint the picture** — give them a flavour of the journey tailored to their level. \
Keep it exciting, not clinical:
   - Newbie: explain what a starter is like it's a living pet they're about to adopt, \
why temperature and timing make all the difference, and promise them you'll hold their \
hand the whole way.
   - Some experience: quickly sketch the key acts (feed starter → autolyse → bulk ferment \
→ shape → cold proof → bake) and tell them you'll build a custom schedule that fits their life.
   - Seasoned: one punchy line — you'll crunch the numbers on their starter activity and \
Melbourne's forecast to nail the timing.

3. **Kit check** — run through the gear list in a breezy, conversational way. \
Not an audit, more like a friend asking "hey, do you have...?":

   Must-haves (the bake won't happen without these):
{essentials}

   Nice-to-haves (life is easier with them, but there are workarounds):
{nice_to_have}

   If something's missing, don't make it a big deal — just explain what it's for, \
suggest a substitute where one exists (e.g. a snug pot with foil instead of a Dutch oven), \
and move on. If they ask whether their specific substitute is good enough, give them a \
straight honest answer.

4. **Kick things off** — when the vibe check and kit check are done and the user is keen \
to go, call the `SubmitReadiness` tool. No formal confirmation needed — just read the room. \
If they're enthusiastic and have (or are happy to improvise) their gear, that's your cue.

Tone rules:
- Warm, energetic, and a little cheeky — like a friend who really loves bread.
- Short responses. If you can say it in two sentences, do that.
- Never say "proceed", "confirm", "acknowledge", or anything that sounds like a consent form.
- Don't get dragged into gear reviews or shopping advice — if they ask what brand to buy, \
gently steer back to what they already have.\
"""


class SubmitReadiness(BaseModel):
    """Call ONLY when the user has confirmed their experience level,
    understood the baking journey, and acknowledged the checklist."""

    experience_level: str = Field(
        description="User's sourdough experience: 'beginner', 'some_experience', or 'experienced'."
    )
    has_essentials: bool = Field(
        description=(
            "True if the user confirmed they have all essential items;"
            " False if they are missing something but chose to proceed anyway."
        )
    )
    missing_items: str = Field(
        description=(
            "Comma-separated list of essential items the user said they are missing,"
            " or empty string if none."
        )
    )


_llm = None


def _get_llm():
    global _llm
    if _llm is None:
        _llm = make_llm([SubmitReadiness], temperature=LLM_TEMPERATURE, top_p=LLM_TOP_P)
    return _llm


def check_readiness_node(state: AgentState) -> dict:
    if state.get("readiness_complete"):
        return {}

    bot_name = state.get("bot_name") or "Doughy"
    system = READINESS_SYSTEM_PROMPT.format(
        bot_name=bot_name,
        essentials="\n".join(f"   - {item}" for item in ESSENTIALS),
        nice_to_have="\n".join(f"   - {item}" for item in NICE_TO_HAVE),
    )

    # Strip tool-call messages — Gemini rejects history containing tool calls without results
    clean_history = [
        m
        for m in state["messages"]
        if getattr(m, "type", None) in ("human", "ai") and not getattr(m, "tool_calls", None)
    ]
    # Gemini requires at least one human message
    history = clean_history or [{"role": "user", "content": "Hi, I want to bake sourdough bread."}]
    response = _get_llm().invoke([{"role": "system", "content": system}] + history)

    tool_calls = getattr(response, "tool_calls", []) or []
    submit_call = next((tc for tc in tool_calls if tc["name"] == SubmitReadiness.__name__), None)

    if submit_call:
        args = submit_call["args"]
        return {
            "messages": [response],
            "readiness_complete": True,
            "user_experience_level": args["experience_level"],
            "current_node": Node.COLLECT_BAKE_CONTEXT,
        }

    return {
        "messages": [response],
        "current_node": Node.CHECK_READINESS,
    }


def route_after_check_readiness(state: AgentState) -> str:
    if state.get("readiness_complete"):
        return Node.COLLECT_BAKE_CONTEXT
    return END
