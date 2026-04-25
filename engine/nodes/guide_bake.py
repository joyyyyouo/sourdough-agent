from state import AgentState


def guide_bake_node(state: AgentState) -> dict:
    """
    Step-by-step check-in during the active bake.

    Presents the next uncompleted step to the user, pauses for their check-in
    using interrupt(), and routes to diagnose_issue if they report a problem.

    Inputs:  state["schedule"], state["completed_steps"], state["weather_scraped_at"]
    Returns: completed_steps update, or current_node=Node.DIAGNOSE_ISSUE on issue
    """
    raise NotImplementedError("guide_bake node is not yet implemented")


def route_after_guide_bake(state: AgentState) -> str:
    raise NotImplementedError("route_after_guide_bake is not yet implemented")
