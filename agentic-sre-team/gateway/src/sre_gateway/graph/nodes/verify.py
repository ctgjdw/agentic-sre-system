from pydantic import BaseModel, Field
from sqlalchemy import select

from sre_gateway.db.models import Artifact, EvidenceRow
from sre_gateway.graph.deps import GraphDeps
from sre_gateway.llm.json_call import call_llm_json

SYSTEM = ("You are the citation verifier. For each claim, decide whether the cited "
          "evidence excerpts actually support it. Be strict: unsupported means the "
          "excerpt does not state or imply the claim.")


class ClaimCheck(BaseModel):
    idx: int
    supported: bool
    reason: str = ""


class VerifyOut(BaseModel):
    results: list[ClaimCheck] = Field(default_factory=list)


def _cited_eids(structured: dict) -> set[str]:
    eids: set[str] = set()
    for key in ("causal_chain", "timeline", "alternatives", "claims"):
        for item in structured.get(key, []):
            eids.update(item.get("eids", []))
    return eids


def make_verify(deps: GraphDeps):
    async def verify(state: dict) -> dict:
        case_id = state["case_id"]
        structured = state["rca"]["structured"]
        async with deps.sessionmaker() as s:
            rows = (await s.execute(
                select(EvidenceRow).where(EvidenceRow.case_id == case_id))).scalars().all()
        by_eid = {r.eid: r.excerpt for r in rows}

        failures = [{"claim": f"citation {eid}",
                     "reason": f"cited evidence {eid} does not exist"}
                    for eid in sorted(_cited_eids(structured) - set(by_eid))]

        claims = structured.get("claims", [])
        if claims and not failures:
            tier = deps.manifests["verify"].tier
            model_id, pricing = deps.models.describe(tier)
            listing = "\n".join(
                f"{i}. CLAIM: {c['text']}\n   EVIDENCE: " +
                " | ".join(f"{e}: {by_eid.get(e, '')[:300]}" for e in c.get("eids", []))
                for i, c in enumerate(claims))
            out = await call_llm_json(deps.models.chat(tier, "verify"), system=SYSTEM,
                                      user=f"Verify each claim:\n{listing}",
                                      schema=VerifyOut, audit=deps.audit, node="verify",
                                      case_id=case_id, model_id=model_id, pricing=pricing)
            for r in out.results:
                if not r.supported and r.idx < len(claims):
                    failures.append({"claim": claims[r.idx]["text"], "reason": r.reason})

        verification = {"verified": not failures, "checked": len(claims),
                        "failures": failures}
        async with deps.sessionmaker() as s:
            art = await s.get(Artifact, state["rca"]["artifact_id"])
            art.verification = verification
            await s.commit()

        update: dict = {"verification": verification}
        if failures:
            update["context_notes"] = [
                "Citation verification failed; fix these in the redraft: "
                + "; ".join(f"{f['claim']} ({f['reason']})" for f in failures)]
        return update

    return verify
