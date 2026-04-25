from langgraph.graph import END, StateGraph

from engine.nodes.adjust_schedule import adjust_schedule_node
from engine.nodes.check_commitment import check_commitment_node, route_after_check_commitment
from engine.nodes.check_readiness import check_readiness_node, route_after_check_readiness
from engine.nodes.collect_bake_context import collect_bake_context_node, route_after_collect_bake_context
from engine.nodes.diagnose_issue import diagnose_issue_node
from engine.nodes.estimate_timeline import estimate_timeline_node
from engine.nodes.guide_bake import guide_bake_node, route_after_guide_bake
from state import AgentState, Node


def build_graph(checkpointer=None):
    builder = StateGraph(AgentState)

    builder.add_node(Node.CHECK_READINESS, check_readiness_node)
    builder.add_node(Node.COLLECT_BAKE_CONTEXT, collect_bake_context_node)
    builder.add_node(Node.ESTIMATE_TIMELINE, estimate_timeline_node)
    builder.add_node(Node.CHECK_COMMITMENT, check_commitment_node)
    builder.add_node(Node.ADJUST_SCHEDULE, adjust_schedule_node)
    builder.add_node(Node.GUIDE_BAKE, guide_bake_node)
    builder.add_node(Node.DIAGNOSE_ISSUE, diagnose_issue_node)

    builder.set_entry_point(Node.CHECK_READINESS)

    builder.add_conditional_edges(
        Node.CHECK_READINESS,
        route_after_check_readiness,
        {Node.COLLECT_BAKE_CONTEXT: Node.COLLECT_BAKE_CONTEXT, END: END},
    )
    builder.add_conditional_edges(
        Node.COLLECT_BAKE_CONTEXT,
        route_after_collect_bake_context,
        {Node.ESTIMATE_TIMELINE: Node.ESTIMATE_TIMELINE, END: END},
    )
    builder.add_edge(Node.ESTIMATE_TIMELINE, Node.CHECK_COMMITMENT)
    builder.add_conditional_edges(
        Node.CHECK_COMMITMENT,
        route_after_check_commitment,
        {Node.ADJUST_SCHEDULE: Node.ADJUST_SCHEDULE, Node.GUIDE_BAKE: Node.GUIDE_BAKE},
    )
    # After adjusting, re-present the updated schedule for confirmation
    builder.add_edge(Node.ADJUST_SCHEDULE, Node.CHECK_COMMITMENT)
    builder.add_conditional_edges(
        Node.GUIDE_BAKE,
        route_after_guide_bake,
        {Node.DIAGNOSE_ISSUE: Node.DIAGNOSE_ISSUE, END: END},
    )
    # Diagnosis always feeds into adjust_schedule to update the remaining schedule
    builder.add_edge(Node.DIAGNOSE_ISSUE, Node.ADJUST_SCHEDULE)

    return builder.compile(checkpointer=checkpointer)
