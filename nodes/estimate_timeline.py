from state import AgentState


def estimate_timeline_node(state: AgentState) -> dict:
    """
    Generates an hourly baking schedule from intake data + weather forecasts.

    Inputs: state["intake"], state["bake_session_id"]
    Returns: messages, schedule, current_node=Node.CHECK_COMMITMENT
    """
    raise NotImplementedError("estimate_timeline node is not yet implemented")
