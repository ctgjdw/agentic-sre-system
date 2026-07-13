from langgraph.graph import END
from langgraph.types import Send

INCIDENT_WORKERS = ["metrics_worker", "logs_worker", "infra_worker", "changes_worker"]
PIPELINE_WORKERS = ["ci_worker", "changes_worker"]
MAX_ROUNDS = 2


def _halted(state: dict) -> bool:
    return bool(state.get("halt"))


def route_after_triage(state: dict) -> str:
    if _halted(state):
        return "park"
    return END if state.get("non_incident") else "plan"


def fan_out(state: dict) -> list[Send]:
    """Deterministic worker fan-out (spec section 4). Runs as plan's conditional edge."""
    if _halted(state):
        return [Send("park", state)]
    if state.get("kind") == "pipeline_failure":
        workers = list(PIPELINE_WORKERS)
        if any(r.get("needs_infra") for r in state.get("worker_reports", [])):
            workers.append("infra_worker")
    elif state.get("effort") == "low":
        workers = ["metrics_worker"]
    else:
        workers = list(INCIDENT_WORKERS)
    payload = {k: v for k, v in state.items()
               if k not in ("evidence", "worker_reports")}  # workers append, never replay
    return [Send(w, payload) for w in workers]


def route_after_synthesize(state: dict) -> str:
    if _halted(state):
        return "park"
    if state.get("need_more") and state.get("round", 1) < MAX_ROUNDS:
        return "plan"
    return "rca"


def route_after_verify(state: dict) -> str:
    if _halted(state):
        return "park"
    verification = state.get("verification") or {}
    if not verification.get("verified", False) and not state.get("repair_used"):
        return "rca"
    return "gate_rca"


def route_after_gate_rca(state: dict) -> str:
    if _halted(state):
        return "park"
    decision = (state.get("gate_rca") or {}).get("decision", "reject")
    return "remediate" if decision in ("approve", "approve_with_edits") else "rca"


def route_after_gate_runbook(state: dict) -> str:
    if _halted(state):
        return "park"
    decision = (state.get("gate_runbook") or {}).get("decision", "reject")
    return "publish" if decision in ("approve", "approve_with_edits") else "remediate"
