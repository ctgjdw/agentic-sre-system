from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select, update

from sre_gateway.db.models import Case, Hypothesis, SignalRow
from sre_gateway.environment import EnvironmentConfig
from sre_gateway.graph.deps import GraphDeps
from sre_gateway.llm.json_call import call_llm_json
from sre_gateway.manifests import assert_tool_allowed
from sre_gateway.retrieval import search_learnings, search_runbooks


def build_system(env: EnvironmentConfig) -> str:
    """SUT-aware prompts render from the environment descriptor (locked decision 15)."""
    return (
        "You are the triage agent of an SRE team.\n"
        f"{env.prompt_block()}\n"
        "Classify the incoming signal, propose severity (1=worst) and investigation "
        "effort, and seed 3-6 distinct candidate hypotheses. If this is clearly not "
        "an incident or pipeline failure, say so with a short canned reply."
    )


class TriageOut(BaseModel):
    is_incident: bool = True
    title: str
    severity: int = Field(ge=1, le=4, default=3)
    effort: Literal["low", "medium", "high"] = "medium"
    failure_class: Literal["code", "test", "config", "dependency", "infra_runner",
                           "flaky", "permissions"] | None = None
    hypotheses: list[str] = Field(default_factory=list, max_length=6)
    canned_reply: str | None = None


def make_triage(deps: GraphDeps):
    async def triage(state: dict) -> dict:
        case_id = state["case_id"]
        async with deps.sessionmaker() as s:
            case = await s.get(Case, case_id)
            signals = (await s.execute(
                select(SignalRow).where(SignalRow.case_id == case_id)
                .order_by(SignalRow.received_at))).scalars().all()
        primary = next((x for x in signals if x.is_primary), signals[0])

        assert_tool_allowed(deps.manifests, "triage", "learning_search")
        assert_tool_allowed(deps.manifests, "triage", "runbook_search")
        learnings = await search_learnings(deps.sessionmaker, deps.models.embed,
                                           primary.summary)
        runbooks = await search_runbooks(deps.sessionmaker, deps.models.embed,
                                         primary.summary)
        # the query-hint half of the learning loop (spec section 4): decisive
        # queries from similar past cases flow into the evidence workers' prompts
        query_hints = [q for hit in learnings
                       for q in hit.get("decisive_queries", [])][:6]

        tier = deps.manifests["triage"].tier
        model_id, pricing = deps.models.describe(tier)
        user = (
            f"Case {case.display_id} (kind: {case.kind}).\n"
            f"Signals:\n" + "\n".join(
                f"- [{x.source}] {x.summary} labels={x.labels}" for x in signals) +
            f"\n\nPrior learnings (seed hypotheses from confirmed causes):\n{learnings}\n"
            f"Matching runbooks:\n{runbooks}\n"
            f"Pipeline-failure cases must set failure_class."
        )
        out = await call_llm_json(deps.models.chat(tier, "triage"),
                                  system=build_system(deps.environment),
                                  user=user, schema=TriageOut, audit=deps.audit,
                                  node="triage", case_id=case_id,
                                  model_id=model_id, pricing=pricing)

        if not out.is_incident:
            async with deps.sessionmaker() as s:
                await s.execute(update(Case).where(Case.id == case_id).values(
                    status="closed", phase="closed", closed_at=datetime.now(UTC),
                    title=out.title or case.title))
                await s.commit()
            await deps.channel.send(
                f"{case.display_id}: not an incident. {out.canned_reply or ''}".strip())
            return {"non_incident": True}

        hypotheses = [{"hid": f"H{i + 1}", "statement": text, "status": "open",
                       "confidence": 0.25} for i, text in enumerate(out.hypotheses)]
        async with deps.sessionmaker() as s:
            await s.execute(update(Case).where(Case.id == case_id).values(
                title=out.title, severity=out.severity, effort=out.effort,
                failure_class=out.failure_class, status="open"))
            # Upsert, not insert: a checkpoint replay after a mid-node crash, or a
            # re-triage of a resumed parked case, re-runs triage against the same
            # (case_id, hid) pairs. A plain insert would IntegrityError on the unique
            # index instead of just re-seeding the board (mirrors synthesize's upsert).
            for h in hypotheses:
                existing = (await s.execute(
                    select(Hypothesis).where(Hypothesis.case_id == case_id,
                                             Hypothesis.hid == h["hid"]))).scalar_one_or_none()
                if existing:
                    existing.statement = h["statement"]
                    existing.status, existing.confidence, existing.round = "open", h["confidence"], 0
                else:
                    s.add(Hypothesis(case_id=case_id, hid=h["hid"], statement=h["statement"],
                                     confidence=h["confidence"], round=0))
            await s.commit()

        await deps.channel.send(
            f"Alert received: {out.title}. Opened {case.display_id}, SEV-{out.severity} "
            f"proposed. Investigating ({out.effort} effort).")
        return {"title": out.title, "severity": out.severity, "effort": out.effort,
                "failure_class": out.failure_class, "hypotheses": hypotheses,
                "kind": case.kind, "display_id": case.display_id, "round": 0,
                "query_hints": query_hints, "non_incident": False}

    return triage
