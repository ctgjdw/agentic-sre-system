from pydantic import BaseModel, Field
from sqlalchemy import func, select

from sre_gateway.db.models import Artifact, EvidenceRow
from sre_gateway.graph.deps import GraphDeps
from sre_gateway.llm.json_call import call_llm_json

SYSTEM = (
    "You are the RCA agent. Produce a root-cause analysis. Order matters: immediate "
    "mitigation FIRST (a reviewer under pressure reads only that), then the root cause "
    "as a causal chain, blast radius, incident timeline, ranked alternatives with why "
    "they were rejected, and monitoring gaps. EVERY claim must cite evidence ids (eids) "
    "that exist in the evidence list. Confidence reflects the hypothesis board."
)


class CausalStep(BaseModel):
    step: str
    eids: list[str] = Field(default_factory=list)


class TimelineEntry(BaseModel):
    ts: str
    text: str
    eids: list[str] = Field(default_factory=list)


class Alternative(BaseModel):
    statement: str
    why_rejected: str
    eids: list[str] = Field(default_factory=list)


class Claim(BaseModel):
    text: str
    eids: list[str] = Field(default_factory=list)


class RcaOut(BaseModel):
    mitigation_md: str
    causal_chain: list[CausalStep] = Field(default_factory=list)
    blast_radius_md: str = ""
    timeline: list[TimelineEntry] = Field(default_factory=list)
    alternatives: list[Alternative] = Field(default_factory=list)
    monitoring_gaps_md: str = ""
    claims: list[Claim] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1, default=0.5)


def _cite(eids: list[str]) -> str:
    return " ".join(f"[{e}]" for e in eids)


def render_rca_md(out: RcaOut) -> str:
    lines = ["## Immediate mitigation", out.mitigation_md, "", "## Root cause"]
    lines += [f"{i + 1}. {s.step} {_cite(s.eids)}" for i, s in enumerate(out.causal_chain)]
    lines += ["", "## Blast radius", out.blast_radius_md, "", "## Timeline"]
    lines += [f"- {t.ts} - {t.text} {_cite(t.eids)}" for t in out.timeline]
    lines += ["", "## Alternatives considered and rejected"]
    lines += [f"- {a.statement}: {a.why_rejected} {_cite(a.eids)}" for a in out.alternatives]
    lines += ["", "## Monitoring gaps", out.monitoring_gaps_md]
    return "\n".join(lines)


def make_rca(deps: GraphDeps):
    async def rca(state: dict) -> dict:
        case_id = state["case_id"]
        async with deps.sessionmaker() as s:
            evidence = (await s.execute(
                select(EvidenceRow).where(EvidenceRow.case_id == case_id)
                .order_by(EvidenceRow.eid))).scalars().all()
            prev = (await s.execute(
                select(func.max(Artifact.version)).where(Artifact.case_id == case_id,
                                                         Artifact.kind == "rca"))
                    ).scalar_one() or 0

        tier = deps.manifests["rca"].tier
        model_id, pricing = deps.models.describe(tier)
        ev_text = "\n".join(f"- {e.eid} [{e.toolset}] query: {e.invocation[:200]} -> "
                            f"{e.excerpt[:300]}" for e in evidence)
        board = "\n".join(f"- {h['hid']} [{h.get('status')}] conf={h.get('confidence')} "
                          f"{h['statement']}" for h in state.get("hypotheses", []))
        user = (f"Case: {state.get('title', '')} (SEV-{state.get('severity', 3)}, "
                f"kind {state.get('kind', 'incident')}).\nHypothesis board:\n{board}\n"
                f"Evidence:\n{ev_text}\n"
                f"Reviewer / verifier notes to address: {state.get('context_notes', [])}")
        out = await call_llm_json(deps.models.chat(tier, "rca"), system=SYSTEM, user=user,
                                  schema=RcaOut, audit=deps.audit, node="rca",
                                  case_id=case_id, model_id=model_id, pricing=pricing)

        async with deps.sessionmaker() as s:
            art = Artifact(case_id=case_id, kind="rca", version=prev + 1,
                           structured=out.model_dump(), body_md=render_rca_md(out),
                           model_id=model_id)
            s.add(art)
            await s.commit()
            artifact_id = art.id
        return {"rca": {"artifact_id": artifact_id, "version": prev + 1,
                        "structured": out.model_dump(), "confidence": out.confidence},
                "repair_used": bool(state.get("verification"))}

    return rca
