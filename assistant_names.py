import random

ASSISTANT_NAMES = [
    "Floury Potter",
    "Dougharella",
    "Bready McBreadface",
    "Crustopher",
    "Dough-natello",
    "Cinnabun",
    "Flourence",
    "Glutenberg",
    "Yeastopher",
    "Bun Solo",
    "Loafy Skywalker",
    "Dough-bi-Wan",
    "Breadwin",
    "Kneady",
    "Breadnard",
    "Rye-an",
    "Dough-lores",
    "Proofie",
    "Artie San",
    "Crumbelina",
]

ADJECTIVES = [
    "Bubbly",
    "Crusty",
    "Tangy",
    "Proofed",
    "Fermented",
    "Sourdough-Powered",
    "Wild-Yeast",
    "Gassy",
    "Floury",
    "Chewy",
    "Crispy",
    "Rustic",
    "Over-Proofed",
    "Under-Proofed",
    "Toasty",
    "Artisanal",
    "Hydrated",
    "Slack",
    "Stiff",
    "Golden",
]


def generate_assistant_name() -> str:
    adjective = random.choice(ADJECTIVES)
    name = random.choice(ASSISTANT_NAMES)
    return f"The {adjective} {name}"
