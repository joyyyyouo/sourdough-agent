from langchain_core.messages import BaseMessage


def clean_history(messages: list[BaseMessage], seed: str) -> list:
    """Strip tool-call messages and return a history safe to send to Gemini.

    Gemini rejects conversation history that contains tool calls without
    corresponding tool results. If the filtered list is empty, returns a
    minimal seed message so Gemini always has at least one human turn.
    """
    filtered = [
        m
        for m in messages
        if getattr(m, "type", None) in ("human", "ai") and not getattr(m, "tool_calls", None)
    ]
    return filtered or [{"role": "user", "content": seed}]
