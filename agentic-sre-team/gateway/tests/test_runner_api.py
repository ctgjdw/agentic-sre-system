import asyncio
import hashlib
import hmac
from pathlib import Path


def _sig(body: str) -> str:
    return hmac.new(b"topsecret", body.encode(), hashlib.sha256).hexdigest()


async def _open_case(client) -> dict:
    body = (Path(__file__).parent / "fixtures/grafana_webhook.json").read_text()
    res = await client.post("/api/webhooks/grafana", content=body,
                            headers={"X-Grafana-Alerting-Signature": _sig(body)})
    return res.json()["results"][0]


async def _wait_status(client, case_id, status, phase=None, timeout=30):
    # `runner.resume`/`runner.start` are fire-and-forget: a decision POST can return
    # before the background task has moved off the gate it was already parked at, so
    # polling for `status` alone races when two gates share the same status
    # ("waiting_approval"). Passing `phase` disambiguates which gate we're waiting for.
    for _ in range(timeout * 10):
        detail = (await client.get(f"/api/cases/{case_id}")).json()
        if detail["case"]["status"] == status and (
                phase is None or detail["case"]["phase"] == phase):
            return detail
        await asyncio.sleep(0.1)
    raise AssertionError(f"case never reached {status}/{phase}: {detail['case']}")


async def test_webhook_drives_case_to_gate1_and_decision_to_gate2(client, db):
    opened = await _open_case(client)
    detail = await _wait_status(client, opened["case_id"], "waiting_approval",
                                phase="gate_rca")
    assert any(a["kind"] == "rca" and a["verification"]["verified"]
               for a in detail["artifacts"])
    assert {h["hid"] for h in detail["hypotheses"]} >= {"H1", "H2", "H3"}
    assert len(detail["evidence"]) == 8  # 4 workers x 2 fixture tool calls

    res = await client.post(f"/api/cases/{opened['case_id']}/decision", json={
        "gate": "rca", "decision": "approve", "decided_by": "alex.goh"})
    assert res.status_code == 200
    detail = await _wait_status(client, opened["case_id"], "waiting_approval",
                                phase="gate_runbook")

    res = await client.post(f"/api/cases/{opened['case_id']}/decision", json={
        "gate": "runbook", "decision": "approve", "decided_by": "alex.goh"})
    detail = await _wait_status(client, opened["case_id"], "closed")
    assert detail["case"]["status"] == "closed"


async def test_decision_on_wrong_gate_is_409(client, db):
    opened = await _open_case(client)
    await _wait_status(client, opened["case_id"], "waiting_approval")
    res = await client.post(f"/api/cases/{opened['case_id']}/decision", json={
        "gate": "runbook", "decision": "approve", "decided_by": "x"})
    assert res.status_code == 409


async def test_stream_replays_events(client, db):
    opened = await _open_case(client)
    await _wait_status(client, opened["case_id"], "waiting_approval")
    async with client.stream("GET",
                             f"/api/cases/{opened['case_id']}/stream") as res:
        events = []
        async for line in res.aiter_lines():
            if line.startswith("event:"):
                events.append(line.split(":", 1)[1].strip())
            if "gate_waiting" in events:
                break
    assert "node_start" in events and "tool_call" in events


async def test_governance_and_activity_read_models(client, db):
    opened = await _open_case(client)
    await _wait_status(client, opened["case_id"], "waiting_approval")
    gov = (await client.get("/api/governance")).json()
    assert gov["paused"] is False
    agents = {a["agent"]: a for a in gov["agents"]}
    assert agents["triage"]["spend_today"] > 0
    act = (await client.get("/api/activity?hours=24")).json()
    assert act["cases"][0]["display_id"] == "CASE-0001"
    assert sum(b["signals"] for b in act["buckets"]) >= 1


async def test_halt_at_remediate_parks_not_runner_error(client, db):
    # A guarded()-node halt (pause, budget breach) returned right after the gate-1
    # approval must route to park, not fall through the unconditional remediate ->
    # gate_runbook edge (which KeyErrors on the missing "runbook" key and gets
    # mis-recorded as a generic "runner error").
    opened = await _open_case(client)
    await _wait_status(client, opened["case_id"], "waiting_approval", phase="gate_rca")
    await client.post("/api/governance/pause", json={"paused": True, "actor": "t"})
    res = await client.post(f"/api/cases/{opened['case_id']}/decision", json={
        "gate": "rca", "decision": "approve", "decided_by": "alex.goh"})
    assert res.status_code == 200
    detail = await _wait_status(client, opened["case_id"], "needs_human")
    assert detail["case"]["halt_reason"] == "paused"
    await client.post("/api/governance/pause", json={"paused": False, "actor": "t"})


async def test_halt_at_publish_parks_not_stranded(client, db):
    # Same bug at the publish -> END edge: a halt there must not silently finish the
    # run with the case stuck open at gate_runbook, never paged.
    opened = await _open_case(client)
    await _wait_status(client, opened["case_id"], "waiting_approval", phase="gate_rca")
    await client.post(f"/api/cases/{opened['case_id']}/decision", json={
        "gate": "rca", "decision": "approve", "decided_by": "alex.goh"})
    await _wait_status(client, opened["case_id"], "waiting_approval", phase="gate_runbook")
    await client.post("/api/governance/pause", json={"paused": True, "actor": "t"})
    res = await client.post(f"/api/cases/{opened['case_id']}/decision", json={
        "gate": "runbook", "decision": "approve", "decided_by": "alex.goh"})
    assert res.status_code == 200
    detail = await _wait_status(client, opened["case_id"], "needs_human")
    assert detail["case"]["halt_reason"] == "paused"
    await client.post("/api/governance/pause", json={"paused": False, "actor": "t"})


async def test_resume_redrives_parked_case_past_needs_human(client_resume, db):
    from sre_gateway.budget import BudgetEnforcer, CaseBudget

    client, app = client_resume
    # A near-zero token budget parks the case right after triage's single LLM call,
    # before plan/workers/synthesize/rca/verify ever run.
    app.state.deps.budget = BudgetEnforcer(db, CaseBudget(tokens=10, tool_calls=60,
                                                           wall_clock_s=900))
    opened = await _open_case(client)
    detail = await _wait_status(client, opened["case_id"], "needs_human")
    assert "budget" in (detail["case"]["halt_reason"] or "")

    # Restore headroom before resuming so the re-investigation can actually complete.
    app.state.deps.budget = BudgetEnforcer(db, CaseBudget(tokens=500_000, tool_calls=60,
                                                           wall_clock_s=900))
    res = await client.post(f"/api/cases/{opened['case_id']}/resume",
                            json={"actor": "alex.goh"})
    assert res.status_code == 200
    detail = await _wait_status(client, opened["case_id"], "waiting_approval",
                                phase="gate_rca")
    assert detail["case"]["halt_reason"] is None
    assert detail["case"]["round"] == 1  # re-triaged and re-ran the pipeline from scratch

    # Resuming a case that isn't parked is rejected.
    res = await client.post(f"/api/cases/{opened['case_id']}/resume",
                            json={"actor": "alex.goh"})
    assert res.status_code == 409


async def test_concurrent_decisions_only_one_wins(client, db):
    from sqlalchemy import select

    from sre_gateway.db.models import Approval

    opened = await _open_case(client)
    await _wait_status(client, opened["case_id"], "waiting_approval", phase="gate_rca")
    body = {"gate": "rca", "decision": "approve", "decided_by": "alex.goh"}
    results = await asyncio.gather(
        client.post(f"/api/cases/{opened['case_id']}/decision", json=body),
        client.post(f"/api/cases/{opened['case_id']}/decision", json=body),
        return_exceptions=True)
    statuses = sorted(r.status_code for r in results)
    assert statuses == [200, 409]
    await _wait_status(client, opened["case_id"], "waiting_approval", phase="gate_runbook")
    async with db() as s:
        approvals = (await s.execute(select(Approval))).scalars().all()
    assert len(approvals) == 1
