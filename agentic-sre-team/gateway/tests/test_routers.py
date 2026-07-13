from langgraph.types import Send

from sre_gateway.graph.routers import (
    fan_out, route_after_synthesize, route_after_triage, route_after_verify,
)


def test_triage_routes_to_plan_or_end_or_park():
    assert route_after_triage({"non_incident": False}) == "plan"
    assert route_after_triage({"non_incident": True}) == "__end__"
    assert route_after_triage({"halt": {"reason": "x"}}) == "park"


def test_fan_out_incident_medium_is_four_workers():
    sends = fan_out({"kind": "incident", "effort": "medium", "case_id": "c"})
    assert {s.node for s in sends} == {"metrics_worker", "logs_worker",
                                       "infra_worker", "changes_worker"}
    assert all(isinstance(s, Send) for s in sends)


def test_fan_out_incident_low_is_one_worker():
    sends = fan_out({"kind": "incident", "effort": "low", "case_id": "c"})
    assert [s.node for s in sends] == ["metrics_worker"]


def test_fan_out_pipeline_failure_is_ci_plus_changes():
    sends = fan_out({"kind": "pipeline_failure", "effort": "medium", "case_id": "c"})
    assert {s.node for s in sends} == {"ci_worker", "changes_worker"}


def test_fan_out_pipeline_adds_infra_when_flagged():
    state = {"kind": "pipeline_failure", "effort": "medium", "case_id": "c",
             "worker_reports": [{"worker": "ci", "needs_infra": True}]}
    assert "infra_worker" in {s.node for s in fan_out(state)}


def test_synthesize_loops_bounded():
    assert route_after_synthesize({"need_more": True, "round": 1}) == "plan"
    assert route_after_synthesize({"need_more": True, "round": 2}) == "rca"
    assert route_after_synthesize({"need_more": False, "round": 1}) == "rca"


def test_verify_repairs_exactly_once():
    failed = {"verification": {"verified": False}, "repair_used": False}
    assert route_after_verify(failed) == "rca"
    assert route_after_verify({"verification": {"verified": False},
                               "repair_used": True}) == "gate_rca"
    assert route_after_verify({"verification": {"verified": True},
                               "repair_used": False}) == "gate_rca"
