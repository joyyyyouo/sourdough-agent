from state import AgentState


def diagnostic_node(state: AgentState) -> dict:
    """
    Diagnoses a mid-bake issue reported by the user before routing to revision.

    Fetches latest weather data, reasons about root cause (weather change,
    timing, technique), and sets diagnosis + revision_type in state.

    Inputs:  state["messages"] (last message is the issue report),
             state["schedule"], state["completed_steps"],
             state["weather_scrape_run_id"]
    Returns: diagnosis, revision_type, current_node="revision"
    """
    raise NotImplementedError("diagnostic node is not yet implemented")
