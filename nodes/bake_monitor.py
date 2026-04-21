from langgraph.graph import END

from state import AgentState


def bake_monitor_node(state: AgentState) -> dict:
    """
    Step-by-step check-in during the active bake.

    Presents the next uncompleted step to the user, pauses for their check-in
    using interrupt(), and routes to diagnostic if they report an issue.

    Inputs:  state["schedule"], state["completed_steps"], state["weather_scraped_at"]
    Returns: completed_steps update, or current_node="diagnostic" on issue
    """
    raise NotImplementedError("bake_monitor node is not yet implemented")


def route_after_bake_monitor(state: AgentState) -> str:
    raise NotImplementedError("route_after_bake_monitor is not yet implemented")
