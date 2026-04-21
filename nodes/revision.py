from state import AgentState


def revision_node(state: AgentState) -> dict:
    """
    Node 4 – revises the schedule around user availability conflicts.

    Inputs: state["schedule"], state["conflicts"], state["bake_session_id"]
    Returns: messages, updated schedule, current_node="end"
    """
    raise NotImplementedError("Node 4 – Revision is not yet implemented")
