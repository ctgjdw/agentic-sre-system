from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/healthz")
async def healthz(request: Request) -> dict:
    components: dict[str, str] = dict(request.app.state.health)
    # A component intentionally turned off is not a degradation.
    status = "ok" if all(v in ("ok", "disabled") for v in components.values()) else "degraded"
    return {"status": status, "service": "sre-gateway", "components": components}
