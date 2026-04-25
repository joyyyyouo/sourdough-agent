import sqlite3

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from config import DB_PATH
from engine.graph import build_graph


class BakingAgentService:
    """Owns all LangGraph interactions.

    UI layer and future HTTP layer call only these methods — no LangGraph
    imports needed outside this file.
    """

    def __init__(self):
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        self._graph = build_graph(SqliteSaver(conn))

    def checkpoint_exists(self, thread_id: str) -> bool:
        snapshot = self._graph.get_state({"configurable": {"thread_id": thread_id}})
        return bool(snapshot and snapshot.values)

    def seed(self, thread_id: str, initial_state: dict) -> None:
        self._graph.invoke(
            initial_state,
            config={"configurable": {"thread_id": thread_id}},
        )

    def get_state(self, thread_id: str) -> dict:
        snapshot = self._graph.get_state({"configurable": {"thread_id": thread_id}})
        return snapshot.values if snapshot else {}

    def send_message(self, thread_id: str, message: str) -> dict:
        cfg = {"configurable": {"thread_id": thread_id}}
        snapshot = self._graph.get_state(cfg)
        try:
            if snapshot.next:
                return self._graph.invoke(Command(resume=message), config=cfg)
            return self._graph.invoke(
                {"messages": [{"role": "user", "content": message}]},
                config=cfg,
            )
        except NotImplementedError:
            # A downstream node isn't implemented yet; the completed node's
            # output is already checkpointed, so return current state.
            return self._graph.get_state(cfg).values
