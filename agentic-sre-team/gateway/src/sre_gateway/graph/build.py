from langgraph.graph import END, START, StateGraph

from sre_gateway.graph.deps import GraphDeps, guarded
from sre_gateway.graph.nodes.gates import make_gate
from sre_gateway.graph.nodes.park import make_park
from sre_gateway.graph.nodes.plan import make_plan
from sre_gateway.graph.nodes.publish import make_publish
from sre_gateway.graph.nodes.rca import make_rca
from sre_gateway.graph.nodes.remediate import make_remediate
from sre_gateway.graph.nodes.synthesize import make_synthesize
from sre_gateway.graph.nodes.triage import make_triage
from sre_gateway.graph.nodes.verify import make_verify
from sre_gateway.graph.nodes.workers import make_worker
from sre_gateway.graph.routers import (
    fan_out, route_after_gate_rca, route_after_gate_runbook, route_after_publish,
    route_after_remediate, route_after_synthesize, route_after_triage, route_after_verify,
)
from sre_gateway.graph.state import CaseState

WORKER_NODES = {"metrics_worker": "metrics", "logs_worker": "logs",
                "infra_worker": "infra", "changes_worker": "changes", "ci_worker": "ci"}


def build_graph(deps: GraphDeps, checkpointer=None):
    g = StateGraph(CaseState)
    g.add_node("triage", guarded(deps, "triage", make_triage(deps)))
    g.add_node("plan", guarded(deps, "plan", make_plan(deps)))
    for node, domain in WORKER_NODES.items():
        g.add_node(node, make_worker(deps, domain))  # parallel branches; budget re-checked at synthesize
    g.add_node("synthesize", guarded(deps, "synthesize", make_synthesize(deps)))
    g.add_node("rca", guarded(deps, "rca", make_rca(deps)))
    g.add_node("verify_citations", guarded(deps, "verify_citations", make_verify(deps)))
    g.add_node("gate_rca", make_gate(deps, "rca"))
    g.add_node("remediate", guarded(deps, "remediate", make_remediate(deps)))
    g.add_node("gate_runbook", make_gate(deps, "runbook"))
    g.add_node("publish", guarded(deps, "publish", make_publish(deps)))
    g.add_node("park", make_park(deps))

    g.add_edge(START, "triage")
    g.add_conditional_edges("triage", route_after_triage,
                            {"plan": "plan", END: END, "park": "park"})
    g.add_conditional_edges("plan", fan_out, list(WORKER_NODES) + ["park"])
    for node in WORKER_NODES:
        g.add_edge(node, "synthesize")
    g.add_conditional_edges("synthesize", route_after_synthesize,
                            {"plan": "plan", "rca": "rca", "park": "park"})
    g.add_edge("rca", "verify_citations")
    g.add_conditional_edges("verify_citations", route_after_verify,
                            {"rca": "rca", "gate_rca": "gate_rca", "park": "park"})
    g.add_conditional_edges("gate_rca", route_after_gate_rca,
                            {"remediate": "remediate", "rca": "rca", "park": "park"})
    g.add_conditional_edges("remediate", route_after_remediate,
                            {"gate_runbook": "gate_runbook", "park": "park"})
    g.add_conditional_edges("gate_runbook", route_after_gate_runbook,
                            {"publish": "publish", "remediate": "remediate", "park": "park"})
    g.add_conditional_edges("publish", route_after_publish, {END: END, "park": "park"})
    g.add_edge("park", END)
    return g.compile(checkpointer=checkpointer)
