from pathlib import Path

from sqlalchemy import select

from sre_gateway.audit import AuditWriter, set_flag
from sre_gateway.budget import BudgetEnforcer, CaseBudget
from sre_gateway.db.models import AuditEvent, Case, EvidenceRow
from sre_gateway.graph.nodes.workers import make_worker

HOLMES_FIXTURES = Path(__file__).parent / "fixtures/holmes"


async def _seed(db, **kw):
    async with db() as s:
        c = Case(display_id="CASE-0001", kind="incident", fingerprint="f", thread_id="t",
                 title="Error rate spike on admin-server", **kw)
        s.add(c)
        await s.commit()
        return c


async def test_metrics_worker_maps_tool_calls_to_evidence(deps, db):
    case = await _seed(db)
    worker = make_worker(deps, "metrics")
    state = {"case_id": case.id, "kind": "incident", "title": case.title,
             "hypotheses": [{"hid": "H1", "statement": "pool exhaustion", "status": "open"},
                            {"hid": "H3", "statement": "cpu saturation", "status": "open"}]}
    update = await worker(state)
    report = update["worker_reports"][0]
    assert report["worker"] == "metrics" and not report["degraded"]
    assert {e["eid"] for e in update["evidence"]} == {"E1", "E2"}
    findings = {f["hid"]: f for f in report["findings"]}
    assert findings["H3"]["direction"] == "against"
    assert findings["H1"]["eids"] == ["E1"]
    async with db() as s:
        rows = (await s.execute(select(EvidenceRow))).scalars().all()
        refreshed = await s.get(Case, case.id)
    assert len(rows) == 2 and refreshed.tool_calls == 2
    assert refreshed.evidence_counter == 2


async def test_parallel_eid_allocation_never_collides(deps, db):
    case = await _seed(db)
    import asyncio

    state = {"case_id": case.id, "kind": "incident", "title": case.title, "hypotheses": []}
    updates = await asyncio.gather(make_worker(deps, "metrics")(state),
                                   make_worker(deps, "logs")(state))
    eids = [e["eid"] for u in updates for e in u["evidence"]]
    assert len(eids) == len(set(eids)) == 4


async def test_holmes_failure_degrades_not_raises(deps, db, monkeypatch):
    case = await _seed(db)
    worker = make_worker(deps, "infra")
    monkeypatch.setenv("FAKE_HOLMES_DIR", "/nonexistent")  # fake server now 404s
    update = await worker({"case_id": case.id, "kind": "incident", "title": "x",
                           "hypotheses": []})
    report = update["worker_reports"][0]
    assert report["degraded"] and update["evidence"] == []


async def test_worker_precheck_pause_skips_holmes(deps, db):
    case = await _seed(db)
    await set_flag(db, "paused", True, actor="t", audit=AuditWriter(db))
    worker = make_worker(deps, "metrics")
    update = await worker({"case_id": case.id, "kind": "incident", "title": case.title,
                           "hypotheses": []})
    report = update["worker_reports"][0]
    assert report["degraded"] is True and report["error"] == "paused"
    assert update["evidence"] == []
    async with db() as s:
        assert (await s.execute(select(EvidenceRow))).scalars().all() == []
        tool_calls = (await s.execute(
            select(AuditEvent).where(AuditEvent.event_type == "tool_call"))).scalars().all()
    assert tool_calls == []  # no Holmes invocation at all, not even a failed one


async def test_worker_precheck_budget_breach_skips_holmes(deps, db):
    case = await _seed(db, tokens_in=1_000_000)
    deps.budget = BudgetEnforcer(db, CaseBudget(tokens=10, tool_calls=60, wall_clock_s=900))
    worker = make_worker(deps, "metrics")
    update = await worker({"case_id": case.id, "kind": "incident", "title": case.title,
                           "hypotheses": []})
    report = update["worker_reports"][0]
    assert report["degraded"] is True and report["error"].startswith("budget:")
    assert update["evidence"] == []
    async with db() as s:
        assert (await s.execute(select(EvidenceRow))).scalars().all() == []


async def test_findings_parse_failure_does_not_burn_evidence_counter(deps, db, monkeypatch):
    # A worker whose LLM reply never parses (out.FindingsOut validation fails) must
    # degrade WITHOUT bumping evidence_counter first - otherwise a permanent gap opens
    # in the case's eid sequence (E3 allocated and never used, say).
    case = await _seed(db)
    monkeypatch.setenv("FAKE_HOLMES_DIR", str(HOLMES_FIXTURES / "worker_parse_failure"))
    worker = make_worker(deps, "metrics")
    update = await worker({"case_id": case.id, "kind": "incident", "title": "x",
                           "hypotheses": []})
    report = update["worker_reports"][0]
    assert report["degraded"] and update["evidence"] == []
    async with db() as s:
        refreshed = await s.get(Case, case.id)
    assert refreshed.evidence_counter == 0
