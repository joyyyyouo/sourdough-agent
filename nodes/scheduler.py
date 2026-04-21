from state import AgentState


def scheduler_node(state: AgentState) -> dict:
    """
    Node 2 – generates an hourly baking schedule from intake data + weather forecasts.

    Inputs: state["intake"], state["bake_session_id"]
    Returns: messages, schedule, current_node="commitment"
    """
    raise NotImplementedError("Node 2 – Scheduler is not yet implemented")
