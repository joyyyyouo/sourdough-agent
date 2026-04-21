from state import AgentState


def commitment_node(state: AgentState) -> dict:
    """
    Presents the schedule to the user and collects conflicts or confirmation.

    Uses interrupt() to pause mid-graph while waiting for user input, allowing
    the session to persist across browser closes and be resumed later.

    Inputs:  state["schedule"], state["bake_session_id"]
    Returns: messages, conflicts list (may be empty on clean confirmation),
             current_node="revision" or "bake_monitor"
    """
    raise NotImplementedError("commitment node is not yet implemented")


def route_after_commitment(state: AgentState) -> str:
    """
    Routes to revision if conflicts were reported, or to bake_monitor when
    the user has confirmed the schedule with no changes needed.
    """
    raise NotImplementedError("route_after_commitment is not yet implemented")
