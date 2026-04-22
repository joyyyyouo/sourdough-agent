from langgraph.graph import END, StateGraph

from nodes.assess_readiness import assess_readiness_node, route_after_readiness
from nodes.bake_monitor import bake_monitor_node, route_after_bake_monitor
from nodes.commitment import commitment_node, route_after_commitment
from nodes.diagnostic import diagnostic_node
from nodes.intake import intake_node, route_after_intake
from nodes.revision import revision_node
from nodes.scheduler import scheduler_node
from state import AgentState


def build_graph(checkpointer=None):
    builder = StateGraph(AgentState)

    builder.add_node("assess_readiness", assess_readiness_node)
    builder.add_node("intake", intake_node)
    builder.add_node("scheduler", scheduler_node)
    builder.add_node("commitment", commitment_node)
    builder.add_node("revision", revision_node)
    builder.add_node("bake_monitor", bake_monitor_node)
    builder.add_node("diagnostic", diagnostic_node)

    builder.set_entry_point("assess_readiness")

    builder.add_conditional_edges(
        "assess_readiness",
        route_after_readiness,
        {"intake": "intake", END: END},
    )
    builder.add_conditional_edges(
        "intake",
        route_after_intake,
        {"scheduler": "scheduler", END: END},
    )
    builder.add_edge("scheduler", "commitment")
    builder.add_conditional_edges(
        "commitment",
        route_after_commitment,
        {"revision": "revision", "bake_monitor": "bake_monitor"},
    )
    # After revision, re-present the updated schedule for confirmation
    builder.add_edge("revision", "commitment")
    builder.add_conditional_edges(
        "bake_monitor",
        route_after_bake_monitor,
        {"diagnostic": "diagnostic", END: END},
    )
    # Diagnosis always feeds into revision to update the remaining schedule
    builder.add_edge("diagnostic", "revision")

    return builder.compile(checkpointer=checkpointer)
