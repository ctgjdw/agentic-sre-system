import operator
from typing import Annotated, TypedDict


class CaseState(TypedDict, total=False):
    case_id: str
    display_id: str
    kind: str
    title: str
    severity: int
    effort: str
    round: int
    failure_class: str | None
    non_incident: bool
    hypotheses: list[dict]            # owned by triage/synthesize only
    evidence: Annotated[list[dict], operator.add]
    worker_reports: Annotated[list[dict], operator.add]
    context_notes: Annotated[list[str], operator.add]
    query_hints: list[str]            # decisive-query hints from case learnings (triage)
    need_more: bool
    rca: dict | None
    verification: dict | None
    repair_used: bool
    runbook: dict | None
    gate_rca: dict | None
    gate_runbook: dict | None
    halt: dict | None
