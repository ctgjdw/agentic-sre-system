import difflib
from datetime import UTC, datetime
from typing import Literal

from langgraph.types import interrupt

from sre_gateway.db.models import Approval, Artifact, Case
from sre_gateway.graph.deps import GraphDeps


def make_gate(deps: GraphDeps, gate: Literal["rca", "runbook"]):
    async def gate_node(state: dict) -> dict:
        case_id = state["case_id"]
        artifact_ref = state["rca" if gate == "rca" else "runbook"]

        # Everything before interrupt() re-runs on resume: keep it idempotent. Stamp
        # waiting_since only the first time we reach this gate (case.waiting_since is
        # already set by the time the resume-replay re-executes this block), so the
        # wall-clock budget can later exclude review time (see BudgetEnforcer.check_case).
        async with deps.sessionmaker() as s:
            case = await s.get(Case, case_id)
            if case.waiting_since is None:
                case.waiting_since = datetime.now(UTC)
            case.status, case.phase = "waiting_approval", f"gate_{gate}"
            await s.commit()

        decision: dict = interrupt({
            "gate": gate, "case_id": case_id, "display_id": state.get("display_id", ""),
            "artifact_id": artifact_ref["artifact_id"], "version": artifact_ref["version"],
        })

        # From here on runs exactly once, after resume.
        verdict = decision.get("decision", "reject")
        async with deps.sessionmaker() as s:
            art = await s.get(Artifact, artifact_ref["artifact_id"])
            diff = None
            if verdict == "approve_with_edits" and decision.get("edited_body_md"):
                art.body_edited_md = decision["edited_body_md"]
                diff = "\n".join(difflib.unified_diff(
                    art.body_md.splitlines(), decision["edited_body_md"].splitlines(),
                    fromfile="drafted", tofile="edited", lineterm=""))
            s.add(Approval(case_id=case_id, artifact_id=art.id, gate=gate,
                           decision=verdict,
                           decided_by=decision.get("decided_by", "unknown"),
                           channel=decision.get("channel", "ui"),
                           annotation=decision.get("annotation", ""), diff=diff))
            case = await s.get(Case, case_id)
            case.status = "open"
            if case.waiting_since is not None:
                case.waited_seconds += int(
                    (datetime.now(UTC) - case.waiting_since).total_seconds())
                case.waiting_since = None
            await s.commit()
        await deps.audit.log("approval", actor=decision.get("decided_by", "unknown"),
                             case_id=case_id, gate=gate, decision=verdict,
                             channel=decision.get("channel", "ui"),
                             edited=verdict == "approve_with_edits")
        await deps.channel.send(
            f"{state.get('display_id', case_id)}: {gate} {verdict} "
            f"by {decision.get('decided_by', 'unknown')}.")

        # TODO(Phase 4, tracked in .superpowers/sdd/progress.md - Important 5): a crash
        # between the interrupt() resume and this commit leaves the checkpoint holding
        # the consumed decision while case.status/phase never advance past
        # waiting_approval - relaunch_open_cases won't pick it up (status isn't "open"),
        # and a naive retry of this block would double-insert the Approval row. Needs a
        # DB/checkpoint reconciliation pass on startup, deferred out of this fix bundle.
        result: dict = {f"gate_{gate}": decision}
        if verdict == "reject":
            result["context_notes"] = [
                f"Reviewer rejected the {gate}: {decision.get('annotation', '(no note)')}"]
            if gate == "rca":
                result["verification"] = None
                result["repair_used"] = False
        return result

    return gate_node
