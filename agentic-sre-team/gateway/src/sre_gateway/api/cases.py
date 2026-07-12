from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import desc, select

from sre_gateway.db.models import Case, SignalRow

router = APIRouter()


def case_json(c: Case) -> dict:
    return {
        "id": c.id, "display_id": c.display_id, "kind": c.kind, "status": c.status,
        "phase": c.phase, "title": c.title, "severity": c.severity, "effort": c.effort,
        "round": c.round, "failure_class": c.failure_class, "spend_usd": round(c.spend_usd, 4),
        "tokens_in": c.tokens_in, "tokens_out": c.tokens_out, "tool_calls": c.tool_calls,
        "halt_reason": c.halt_reason,
        "created_at": c.created_at.isoformat(),
        "updated_at": c.updated_at.isoformat(),
        "closed_at": c.closed_at.isoformat() if c.closed_at else None,
    }


@router.get("/cases")
async def list_cases(request: Request, status: str | None = None, limit: int = 100) -> dict:
    async with request.app.state.sessionmaker() as s:
        q = select(Case).order_by(desc(Case.created_at)).limit(limit)
        if status:
            q = q.where(Case.status == status)
        cases = (await s.execute(q)).scalars().all()
    return {"cases": [case_json(c) for c in cases]}


@router.get("/cases/{case_id}")
async def get_case(request: Request, case_id: str) -> dict:
    async with request.app.state.sessionmaker() as s:
        case = await s.get(Case, case_id)
        if case is None:
            raise HTTPException(404)
        signals = (await s.execute(
            select(SignalRow).where(SignalRow.case_id == case_id)
            .order_by(SignalRow.received_at)
        )).scalars().all()
    return {"case": case_json(case), "signals": [
        {"id": x.id, "source": x.source, "reporter": x.reporter, "summary": x.summary,
         "fingerprint": x.fingerprint, "labels": x.labels, "is_primary": x.is_primary,
         "attach_reason": x.attach_reason, "received_at": x.received_at.isoformat()}
        for x in signals
    ]}
