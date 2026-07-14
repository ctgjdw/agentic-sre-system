from collections import Counter
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import desc, func, select

from sre_gateway.audit import get_flag, set_flag
from sre_gateway.db.models import AuditEvent, Case

router = APIRouter()

# audit_events.payload->>'reason' values that count as suppression/attach traffic
# (see intake/noise.py and intake/service.py); "opened" (a normal case-open) is excluded.
SUPPRESSION_REASONS = ("dedup", "debounce", "burst", "grouped", "paused")


@router.get("/governance")
async def governance(request: Request) -> dict:
    sm = request.app.state.sessionmaker
    deps = request.app.state.deps
    cutoff = datetime.now(UTC) - timedelta(hours=24)

    agents = []
    for agent, manifest in deps.manifests.items():
        agents.append({
            "agent": agent, "tier": manifest.tier, "tools": manifest.tools,
            "usd_per_day": manifest.budgets.get("usd_per_day", 0.0),
            "spend_today": await deps.budget.agent_spend_today(agent),
        })

    async with sm() as s:
        reasons = (await s.execute(
            select(AuditEvent.payload["reason"].astext).where(
                AuditEvent.event_type.in_(("suppression", "intake")),
                AuditEvent.ts >= cutoff))).scalars().all()
        cases_opened_24h = (await s.execute(
            select(func.count(Case.id)).where(Case.created_at >= cutoff))).scalar_one()

    counts = Counter(reasons)
    return {
        "paused": await get_flag(sm, "paused"),
        "agents": agents,
        "suppression_24h": {r: counts.get(r, 0) for r in SUPPRESSION_REASONS},
        "cases_opened_24h": cases_opened_24h,
        "running_cases": request.app.state.runner.running_count(),
    }


class PauseBody(BaseModel):
    paused: bool
    actor: str


@router.post("/governance/pause")
async def set_pause(request: Request, body: PauseBody) -> dict:
    await set_flag(request.app.state.sessionmaker, "paused", body.paused, body.actor,
                   request.app.state.audit)
    return {"paused": body.paused}


@router.get("/governance/audit")
async def governance_audit(request: Request, limit: int = 100) -> dict:
    async with request.app.state.sessionmaker() as s:
        rows = (await s.execute(
            select(AuditEvent).order_by(desc(AuditEvent.ts)).limit(limit))).scalars().all()
    return {"events": [
        {"id": r.id, "ts": r.ts.isoformat(), "case_id": r.case_id, "actor": r.actor,
         "event_type": r.event_type, "payload": r.payload}
        for r in rows
    ]}
