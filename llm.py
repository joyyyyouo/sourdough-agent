from langchain_google_genai import ChatGoogleGenerativeAI

from config import LLM_MODEL


def make_llm(tools: list | None = None, *, temperature: float = 1.0, top_p: float | None = None):
    kwargs: dict = {"model": LLM_MODEL, "temperature": temperature}
    if top_p is not None:
        kwargs["top_p"] = top_p
    llm = ChatGoogleGenerativeAI(**kwargs)
    return llm.bind_tools(tools) if tools else llm
