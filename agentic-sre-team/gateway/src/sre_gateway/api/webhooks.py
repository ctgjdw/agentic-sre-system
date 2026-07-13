import json

from fastapi import APIRouter, HTTPException, Request

from sre_gateway.intake.grafana import SIGNATURE_HEADER, normalize_grafana, verify_grafana_hmac

router = APIRouter()


@router.post("/webhooks/grafana")
async def grafana_webhook(request: Request) -> dict:
    body = await request.body()
    settings = request.app.state.settings
    if settings.grafana_webhook_secret:
        if not verify_grafana_hmac(settings.grafana_webhook_secret, body,
                                   request.headers.get(SIGNATURE_HEADER)):
            raise HTTPException(status_code=401, detail="bad signature")

    payload = json.loads(body)
    results = []
    for signal in normalize_grafana(payload):
        res = await request.app.state.intake.ingest(signal)
        results.append({"action": res.action, "case_id": res.case_id,
                        "display_id": res.display_id})
    return {"results": results}
