import hashlib
import hmac
from pathlib import Path

FIXTURE = (Path(__file__).parent / "fixtures/grafana_webhook.json").read_text()


def _sig(body: str) -> str:
    return hmac.new(b"topsecret", body.encode(), hashlib.sha256).hexdigest()


async def test_webhook_rejects_bad_signature(client):
    res = await client.post("/api/webhooks/grafana", content=FIXTURE,
                            headers={"X-Grafana-Alerting-Signature": "bad"})
    assert res.status_code == 401


async def test_webhook_opens_case_and_case_api_reads_it(client, db):
    res = await client.post("/api/webhooks/grafana", content=FIXTURE,
                            headers={"X-Grafana-Alerting-Signature": _sig(FIXTURE)})
    assert res.status_code == 200
    result = res.json()["results"][0]
    assert result["action"] == "open" and result["display_id"] == "CASE-0001"

    listed = (await client.get("/api/cases")).json()
    assert listed["cases"][0]["display_id"] == "CASE-0001"

    detail = (await client.get(f"/api/cases/{result['case_id']}")).json()
    assert detail["case"]["title"].startswith("Error rate spike")
    assert len(detail["signals"]) == 1
