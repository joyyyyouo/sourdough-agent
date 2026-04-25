from state import AgentState


def diagnose_issue_node(state: AgentState) -> dict:
    """
    Diagnoses a mid-bake issue reported by the user before routing to adjust_schedule.

    Fetches latest weather data, reasons about root cause (weather change,
    timing, technique), and sets diagnosis + revision_type in state.

    Inputs:  state["messages"] (last message is the issue report),
             state["schedule"], state["completed_steps"],
             state["weather_scrape_run_id"]
    Returns: diagnosis, revision_type, current_node=Node.ADJUST_SCHEDULE
    """
    raise NotImplementedError("diagnose_issue node is not yet implemented")
