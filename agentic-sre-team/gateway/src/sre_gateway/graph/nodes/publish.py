from datetime import UTC, datetime

from pydantic import BaseModel, Field
from sqlalchemy import select, update

from sre_gateway.db.models import Artifact, Case, EvidenceRow
from sre_gateway.graph.deps import GraphDeps
from sre_gateway.llm.json_call import call_llm_json
from sre_gateway.retrieval import index_learning, index_runbook

SYSTEM = ("Distill this closed case into a compact learning for future triage: the "
          "signal signature, the confirmed root cause, the queries/toolsets that "
          "produced decisive evidence, and the false leads.")


class LearningOut(BaseModel):
    signal_signature: str
    confirmed_root_cause: str
    decisive_queries: list[str] = Field(default_factory=list)
    false_leads: list[str] = Field(default_factory=list)


def make_publish(deps: GraphDeps):
    async def publish(state: dict) -> dict:
        case_id = state["case_id"]
        display = state.get("display_id", case_id)
        async with deps.sessionmaker() as s:
            rca = await s.get(Artifact, state["rca"]["artifact_id"])
            runbook = await s.get(Artifact, state["runbook"]["artifact_id"])
            evidence = (await s.execute(
                select(EvidenceRow).where(EvidenceRow.case_id == case_id))).scalars().all()
        rca_body = rca.body_edited_md or rca.body_md
        rb_body = runbook.body_edited_md or runbook.body_md

        # Index the runbook and write the learning FIRST, then announce, then close.
        # Announcing (or closing) before this can complete means a downstream failure
        # parks a case the channel already told everyone was done, and a retry after
        # the fix re-indexes a duplicate runbook.
        await index_runbook(deps.sessionmaker, deps.models.embed,
                            title=f"{display}: {state.get('title', '')}",
                            body_md=rb_body, source_case_id=case_id,
                            tags=[state.get("kind", "incident")])

        supported = [h for h in state.get("hypotheses", []) if h.get("status") == "supported"]
        refuted = [h["statement"] for h in state.get("hypotheses", [])
                   if h.get("status") == "refuted"]
        tier = deps.manifests["learnings"].tier
        model_id, pricing = deps.models.describe(tier)
        out = await call_llm_json(
            deps.models.chat(tier, "learnings"), system=SYSTEM,
            user=(f"Case {display}: {state.get('title', '')}\n"
                  f"Confirmed: {[h['statement'] for h in supported]}\nRefuted: {refuted}\n"
                  f"Evidence invocations: "
                  f"{[e.invocation[:120] for e in evidence][:20]}"),
            schema=LearningOut, audit=deps.audit, node="learnings", case_id=case_id,
            model_id=model_id, pricing=pricing)
        await index_learning(deps.sessionmaker, deps.models.embed, case_id=case_id,
                             signal_signature=out.signal_signature,
                             confirmed_root_cause=out.confirmed_root_cause,
                             decisive_queries=out.decisive_queries,
                             false_leads=out.false_leads)

        await deps.channel.send(f"{display} RCA published:\n{rca_body[:3000]}")
        await deps.channel.send(f"{display} runbook published:\n{rb_body[:3000]}")

        async with deps.sessionmaker() as s:
            await s.execute(update(Case).where(Case.id == case_id).values(
                status="closed", phase="closed", closed_at=datetime.now(UTC)))
            await s.commit()
        await deps.audit.log("publish", actor="publish", case_id=case_id,
                             rca_version=rca.version, runbook_version=runbook.version)
        return {}

    return publish
