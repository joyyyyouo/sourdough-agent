import random
from pathlib import Path

from config import ADJECTIVES_PATH, ASSISTANT_NAMES_PATH


def _load(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def generate_assistant_name() -> str:
    adjective = random.choice(_load(ADJECTIVES_PATH))
    name = random.choice(_load(ASSISTANT_NAMES_PATH))
    return f"The {adjective} {name}"
