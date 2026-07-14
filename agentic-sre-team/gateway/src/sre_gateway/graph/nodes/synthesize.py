from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select

from sre_gateway.db.models import Hypothesis, SignalRow
from sre_gateway.graph.deps import GraphDeps
from sre_gateway.llm.json_call import call_llm_json

SYSTEM = (
    "You are the synthesis agent. Update the hypothesis board from the workers' findings: "
    "mark each hypothesis supported / refuted / open with a confidence in [0,1] grounded "
    "in the evidence ids. Decide whether the evidence suffices for an RCA or one more "
    "bounded investigation round is needed (need_more). Write a one-sentence status "
    "update for the ops channel. For pipeline-failure cases you may revise failure_class."
)


class BoardEntry(BaseModel):
    hid: str
    status: Literal["open", "supported", "refuted"] = "open"
    confidence: float = Field(ge=0, le=1, default=0.0)
    note: str = ""


class SynthesizeOut(BaseModel):
    board: list[BoardEntry]
    new_hypotheses: list[str] = Field(default_factory=list)
    need_more: bool = False
    focus: str | None = None
    failure_class: Literal["code", "test", "config", "dependency", "infra_runner",
                           "flaky", "permissions"] | None = None
    status_update: str = ""


def make_synthesize(deps: GraphDeps):
    async def synthesize(state: dict) -> dict:
        case_id = state["case_id"]
        hypotheses = list(state.get("hypotheses", []))
        best = max((h.get("confidence", 0.0) for h in hypotheses), default=0.0)
        tier = ("frontier" if state.get("severity", 3) <= 2 or best < 0.5
                else deps.manifests["synthesize"].tier)

        async with deps.sessionmaker() as s:  # mid-flight human context (Add context)
            notes = (await s.execute(
                select(SignalRow.summary).where(SignalRow.case_id == case_id,
                                                SignalRow.attach_reason == "human_context")
            )).scalars().all()

        model_id, pricing = deps.models.describe(tier)
        reports = "\n".join(
            f"- [{r['worker']}]{' DEGRADED: ' + r.get('error', '') if r.get('degraded') else ''} "
            f"{r.get('summary', '')} findings={r.get('findings', [])} "
            f"proposed={r.get('proposed_hypotheses', [])}"
            for r in state.get("worker_reports", []))
        evidence = "\n".join(f"- {e['eid']} [{e.get('toolset', '')}] {e.get('excerpt', '')[:300]}"
                             for e in state.get("evidence", []))
        user = (
            f"Round {state.get('round', 1)} of 2. Case: {state.get('title', '')} "
            f"(kind {state.get('kind', 'incident')}, SEV-{state.get('severity', 3)}).\n"
            f"Board:\n" + "\n".join(
                f"- {h['hid']} [{h.get('status', 'open')} conf={h.get('confidence', 0)}] "
                f"{h['statement']}" for h in hypotheses) +
            f"\nWorker reports:\n{reports}\nEvidence:\n{evidence}\n"
            f"Human context notes: {list(state.get('context_notes', [])) + list(notes)}\n"
            "Degraded workers mean missing evidence: reflect that in confidence."
        )
        out = await call_llm_json(deps.models.chat(tier, "synthesize"), system=SYSTEM,
                                  user=user, schema=SynthesizeOut, audit=deps.audit,
                                  node="synthesize", case_id=case_id,
                                  model_id=model_id, pricing=pricing)

        by_hid = {h["hid"]: h for h in hypotheses}
        for entry in out.board:
            if entry.hid in by_hid:
                by_hid[entry.hid].update(status=entry.status, confidence=entry.confidence,
                                         note=entry.note)
        next_index = len(by_hid)
        for stmt in out.new_hypotheses:
            next_index += 1
            by_hid[f"H{next_index}"] = {"hid": f"H{next_index}", "statement": stmt,
                                        "status": "open", "confidence": 0.25, "note": ""}
        merged = list(by_hid.values())

        async with deps.sessionmaker() as s:
            for h in merged:
                existing = (await s.execute(
                    select(Hypothesis).where(Hypothesis.case_id == case_id,
                                             Hypothesis.hid == h["hid"]))).scalar_one_or_none()
                if existing:
                    existing.status, existing.confidence = h["status"], h["confidence"]
                    existing.round = state.get("round", 1)
                else:
                    s.add(Hypothesis(case_id=case_id, hid=h["hid"],
                                     statement=h["statement"], status=h["status"],
                                     confidence=h["confidence"],
                                     round=state.get("round", 1)))
            await s.commit()

        if out.status_update:
            await deps.channel.send(
                f"Early findings on {state.get('display_id', case_id)}: {out.status_update}")

        # context_notes is an operator.add reducer: only hand back notes not already
        # accumulated in state, or a note re-queried every round bloats the prompt
        # with duplicates instead of being added once.
        already = set(state.get("context_notes", []))
        update: dict = {"hypotheses": merged, "need_more": out.need_more,
                        "context_notes": [n for n in notes if n not in already]}
        if out.failure_class:
            update["failure_class"] = out.failure_class
        return update

    return synthesize
