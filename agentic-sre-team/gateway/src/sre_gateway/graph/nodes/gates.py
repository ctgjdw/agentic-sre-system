import difflib
from typing import Literal

from langgraph.types import interrupt
from sqlalchemy import update as sa_update

from sre_gateway.db.models import Approval, Artifact, Case
from sre_gateway.graph.deps import GraphDeps


def make_gate(deps: GraphDeps, gate: Literal["rca", "runbook"]):
    async def gate_node(state: dict) -> dict:
        case_id = state["case_id"]
        artifact_ref = state["rca" if gate == "rca" else "runbook"]

        # Everything before interrupt() re-runs on resume: keep it idempotent.
        async with deps.sessionmaker() as s:
            await s.execute(sa_update(Case).where(Case.id == case_id).values(
                status="waiting_approval", phase=f"gate_{gate}"))
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
            await s.execute(sa_update(Case).where(Case.id == case_id)
                            .values(status="open"))
            await s.commit()
        await deps.audit.log("approval", actor=decision.get("decided_by", "unknown"),
                             case_id=case_id, gate=gate, decision=verdict,
                             channel=decision.get("channel", "ui"),
                             edited=verdict == "approve_with_edits")
        await deps.channel.send(
            f"{state.get('display_id', case_id)}: {gate} {verdict} "
            f"by {decision.get('decided_by', 'unknown')}.")

        result: dict = {f"gate_{gate}": decision}
        if verdict == "reject":
            result["context_notes"] = [
                f"Reviewer rejected the {gate}: {decision.get('annotation', '(no note)')}"]
            if gate == "rca":
                result["verification"] = None
                result["repair_used"] = False
        return result

    return gate_node
