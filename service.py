import dataclasses

from config import DB_PATH
from engine.agent import AgentState, agent_step
from infra.db import init_db, load_checkpoint, save_checkpoint


class BakingAgentService:
    """Owns all agent interactions.

    UI layer and future HTTP layer call only these methods — no engine
    imports needed outside this file.
    """

    def __init__(self):
        # Run schema migrations once at startup; connection is closed immediately.
        conn = init_db(DB_PATH)
        conn.close()

    def _conn(self):
        # Open a fresh connection per call — SQLite connections cannot be shared
        # across threads (Streamlit runs handlers in worker threads).
        return init_db(DB_PATH)

    def checkpoint_exists(self, thread_id: str) -> bool:
        conn = self._conn()
        try:
            return load_checkpoint(conn, thread_id) is not None
        finally:
            conn.close()

    def seed(self, thread_id: str, initial_state: dict) -> None:
        """Create initial AgentState and generate the opening greeting."""
        state = AgentState(
            session_key=initial_state.get("session_key"),
            bot_name=initial_state.get("bot_name"),
            thread_id=thread_id,
        )
        state, _ = agent_step(state, "")
        conn = self._conn()
        try:
            save_checkpoint(conn, thread_id, state.to_json())
        finally:
            conn.close()

    def get_state(self, thread_id: str) -> dict:
        conn = self._conn()
        try:
            state_json = load_checkpoint(conn, thread_id)
        finally:
            conn.close()
        if not state_json:
            return {}
        return AgentState.from_json(state_json).__dict__

    def send_message(self, thread_id: str, message: str) -> dict:
        conn = self._conn()
        try:
            state_json = load_checkpoint(conn, thread_id)
            state = AgentState.from_json(state_json) if state_json else AgentState()
            state, response = agent_step(state, message)
            save_checkpoint(conn, thread_id, state.to_json())
        finally:
            conn.close()

        result = dataclasses.asdict(state)
        result["_response"] = response
        return result
