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
