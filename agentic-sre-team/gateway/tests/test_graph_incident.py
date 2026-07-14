from datetime import UTC, datetime, timedelta

from langgraph.types import Command
from sqlalchemy import select

from sre_gateway.budget import BudgetEnforcer, CaseBudget
from sre_gateway.db.models import (
    Approval, Artifact, Case, CaseLearning, EvidenceRow, Hypothesis, Runbook, SignalRow,
)
from sre_gateway.graph import make_checkpointer
from sre_gateway.graph.build import build_graph


async def _seed(db):
    async with db() as s:
        c = Case(display_id="CASE-0001", kind="incident", fingerprint="grafana:x",
                 thread_id="", title="raw alert")
        s.add(c)
        await s.flush()
        # id is a Python-side default resolved during flush, so thread_id (= case id)
        # can only be assigned once the row has been flushed and case.id is populated.
        c.thread_id = c.id
        s.add(SignalRow(case_id=c.id, source="grafana", kind="incident", is_primary=True,
                        fingerprint="grafana:x",
                        summary="Error rate spike on admin-server /api/v1/users",
                        labels={"service": "admin-server"}))
        await s.commit()
        return c


APPROVE = {"decision": "approve", "decided_by": "alex.goh", "channel": "ui"}


async def test_full_incident_lifecycle(deps, db, pg_url):
    case = await _seed(db)
    async with make_checkpointer(pg_url) as saver:
        graph = build_graph(deps, saver)
        cfg = {"configurable": {"thread_id": case.id}}

        result = await graph.ainvoke({"case_id": case.id, "kind": "incident"}, cfg)
        assert "__interrupt__" in result  # gate 1
        async with db() as s:
            refreshed = await s.get(Case, case.id)
            hypos = {h.hid: h for h in
                     (await s.execute(select(Hypothesis))).scalars().all()}
            rca_art = (await s.execute(select(Artifact).where(
                Artifact.kind == "rca"))).scalars().one()
        assert refreshed.status == "waiting_approval" and refreshed.phase == "gate_rca"
        assert hypos["H2"].status == "supported" and hypos["H3"].status == "refuted"
        assert rca_art.verification["verified"] is True

        result = await graph.ainvoke(Command(resume=APPROVE), cfg)
        assert "__interrupt__" in result  # gate 2

        # fresh graph instance: the gate-2 resume must come purely from the
        # checkpoint (gateway-restart survival, spec section 10)
        graph = build_graph(deps, saver)
        await graph.ainvoke(Command(resume=APPROVE), cfg)
        async with db() as s:
            closed = await s.get(Case, case.id)
            approvals = (await s.execute(select(Approval))).scalars().all()
            assert (await s.execute(select(Runbook))).scalars().one()
            assert (await s.execute(select(CaseLearning))).scalars().one()
        assert closed.status == "closed"
        assert {a.gate for a in approvals} == {"rca", "runbook"}
        assert any("runbook published" in m["text"].lower()
                   for m in deps.channel.sent)


async def test_gate1_rejection_redrafts_with_annotation(deps, db, pg_url):
    case = await _seed(db)
    async with make_checkpointer(pg_url) as saver:
        graph = build_graph(deps, saver)
        cfg = {"configurable": {"thread_id": case.id}}
        await graph.ainvoke({"case_id": case.id, "kind": "incident"}, cfg)
        result = await graph.ainvoke(Command(resume={
            "decision": "reject", "decided_by": "alex.goh", "channel": "ui",
            "annotation": "mitigation is wrong, check the flag name"}), cfg)
        assert "__interrupt__" in result  # back at gate 1 with rca v2
        async with db() as s:
            versions = [a.version for a in (await s.execute(
                select(Artifact).where(Artifact.kind == "rca"))).scalars().all()]
        assert sorted(versions) == [1, 2]


async def test_second_round_runs_when_synthesize_asks(deps_two_rounds, db, pg_url):
    case = await _seed(db)
    async with make_checkpointer(pg_url) as saver:
        graph = build_graph(deps_two_rounds, saver)
        cfg = {"configurable": {"thread_id": case.id}}
        result = await graph.ainvoke({"case_id": case.id, "kind": "incident"}, cfg)
        assert "__interrupt__" in result  # both bounded rounds ran, then gate 1
        async with db() as s:
            refreshed = await s.get(Case, case.id)
            evidence = (await s.execute(select(EvidenceRow))).scalars().all()
        assert refreshed.round == 2      # the second bounded round actually executed
        assert len(evidence) == 16       # 4 workers x 2 fixture tool calls x 2 rounds


async def test_budget_breach_parks_case(deps, db, pg_url):
    deps.budget = BudgetEnforcer(db, CaseBudget(tokens=10, tool_calls=60, wall_clock_s=900))
    case = await _seed(db)
    async with make_checkpointer(pg_url) as saver:
        graph = build_graph(deps, saver)
        cfg = {"configurable": {"thread_id": case.id}}
        result = await graph.ainvoke({"case_id": case.id, "kind": "incident"}, cfg)
        assert "__interrupt__" not in result
        async with db() as s:
            parked = await s.get(Case, case.id)
        assert parked.status == "needs_human"
        assert "budget" in (parked.halt_reason or "")
        assert any("parked" in m["text"] for m in deps.channel.sent)


async def test_wall_clock_excludes_gate_review_time(deps, db, pg_url):
    # A reviewer sitting on gate 1 for far longer than the wall-clock cap must not
    # breach the budget: only time the graph is actively running counts.
    case = await _seed(db)
    async with make_checkpointer(pg_url) as saver:
        graph = build_graph(deps, saver)
        cfg = {"configurable": {"thread_id": case.id}}
        await graph.ainvoke({"case_id": case.id, "kind": "incident"}, cfg)  # -> gate_rca

        long_wait = timedelta(seconds=2000)
        async with db() as s:
            c = await s.get(Case, case.id)
            c.created_at = datetime.now(UTC) - long_wait
            c.waiting_since = datetime.now(UTC) - long_wait
            await s.commit()
        deps.budget = BudgetEnforcer(db, CaseBudget(tokens=500_000, tool_calls=60,
                                                     wall_clock_s=900))

        result = await graph.ainvoke(Command(resume=APPROVE), cfg)
        assert "__interrupt__" in result  # reached gate 2, not parked on wall-clock
        async with db() as s:
            refreshed = await s.get(Case, case.id)
        assert refreshed.status == "waiting_approval" and refreshed.phase == "gate_runbook"
        # gate 1's review credited to waited_seconds; gate 2 has now started its own wait
        assert refreshed.waited_seconds >= 1990
        assert refreshed.waiting_since is not None
