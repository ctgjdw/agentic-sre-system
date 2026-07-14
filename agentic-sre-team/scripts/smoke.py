#!/usr/bin/env python3
"""E2E smoke (spec section 11): canned Grafana payload -> gate 1 -> approve -> gate 2
-> approve -> closed, on the fake profile. Asserts RCA citations resolve to evidence."""
import asyncio
import json
import os
import sys
from pathlib import Path

import httpx

BASE = os.environ.get("SMOKE_BASE", "http://localhost:8080/api")
FIXTURE = Path(__file__).parents[1] / "gateway/tests/fixtures/grafana_webhook.json"


async def wait_for(client, case_id, predicate, label, timeout_s=90):
    for _ in range(timeout_s * 2):
        detail = (await client.get(f"{BASE}/cases/{case_id}")).json()
        if predicate(detail):
            return detail
        await asyncio.sleep(0.5)
    sys.exit(f"FAIL: timed out waiting for {label}; last: {detail['case']}")


async def main() -> None:
    async with httpx.AsyncClient(timeout=30) as client:
        for _ in range(60):  # wait for the gateway to come up
            try:
                if (await client.get(f"{BASE}/healthz")).status_code == 200:
                    break
            except httpx.TransportError:
                await asyncio.sleep(1)
        res = await client.post(f"{BASE}/webhooks/grafana", content=FIXTURE.read_text())
        res.raise_for_status()
        case_id = res.json()["results"][0]["case_id"]
        print(f"opened case {case_id}")

        detail = await wait_for(client, case_id,
                                lambda d: d["case"]["phase"] == "gate_rca", "gate 1")
        rca = next(a for a in detail["artifacts"] if a["kind"] == "rca")
        assert rca["verification"]["verified"], "citations must verify"
        eids = {e["eid"] for e in detail["evidence"]}
        cited = {e for c in rca["structured"]["claims"] for e in c["eids"]}
        assert cited <= eids, f"RCA cites unknown evidence: {cited - eids}"
        print(f"RCA v{rca['version']} verified, cites {sorted(cited)}")

        for gate in ("rca", "runbook"):
            res = await client.post(f"{BASE}/cases/{case_id}/decision", json={
                "gate": gate, "decision": "approve", "decided_by": "smoke"})
            res.raise_for_status()
            await wait_for(client, case_id,
                           lambda d, g=gate: d["case"]["phase"] != f"gate_{g}",
                           f"past gate {gate}")
        await wait_for(client, case_id, lambda d: d["case"]["status"] == "closed", "close")
        print("PASS: case closed with published artifacts")


if __name__ == "__main__":
    asyncio.run(main())
