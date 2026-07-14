from sqlalchemy import select

from sre_gateway.db.models import Case, EvidenceRow
from sre_gateway.graph.nodes.workers import make_worker


async def _seed(db):
    async with db() as s:
        c = Case(display_id="CASE-0001", kind="incident", fingerprint="f", thread_id="t",
                 title="Error rate spike on admin-server")
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
