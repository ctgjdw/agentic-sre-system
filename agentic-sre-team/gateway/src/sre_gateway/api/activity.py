from collections import Counter
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import desc, select

from sre_gateway.db.models import AuditEvent, Case, SignalRow

router = APIRouter()


def _bucket(ts: datetime) -> datetime:
    return ts.replace(minute=30 * (ts.minute // 30), second=0, microsecond=0)


@router.get("/activity")
async def activity(request: Request, hours: int = 24) -> dict:
    sm = request.app.state.sessionmaker
    now = datetime.now(UTC)
    cutoff = now - timedelta(hours=hours)
    async with sm() as s:
        signal_times = (await s.execute(
            select(SignalRow.received_at).where(SignalRow.received_at >= cutoff)
        )).scalars().all()
        suppressed_times = (await s.execute(
            select(AuditEvent.ts).where(AuditEvent.event_type == "suppression",
                                        AuditEvent.ts >= cutoff)
        )).scalars().all()
        cases = (await s.execute(
            select(Case).where(Case.created_at >= cutoff)
            .order_by(desc(Case.created_at))
        )).scalars().all()
        annotations = (await s.execute(
            select(AuditEvent).where(AuditEvent.event_type == "annotation",
                                     AuditEvent.ts >= cutoff)
            .order_by(desc(AuditEvent.ts))
        )).scalars().all()

    signal_counts = Counter(_bucket(t) for t in signal_times)
    suppressed_counts = Counter(_bucket(t) for t in suppressed_times)
    bucket_ts = []
    t = _bucket(cutoff)
    while t <= now:
        bucket_ts.append(t)
        t += timedelta(minutes=30)

    return {
        "buckets": [{"ts": b.isoformat(), "signals": signal_counts.get(b, 0),
                     "suppressed": suppressed_counts.get(b, 0)} for b in bucket_ts],
        "cases": [{"id": c.id, "display_id": c.display_id, "severity": c.severity,
                   "kind": c.kind, "created_at": c.created_at.isoformat()} for c in cases],
        "annotations": [{"ts": a.ts.isoformat(), "text": a.payload.get("text", ""),
                         "kind": a.payload.get("kind", "")} for a in annotations],
    }


class AnnotationBody(BaseModel):
    text: str
    kind: str = ""


@router.post("/activity/annotations")
async def add_annotation(request: Request, body: AnnotationBody) -> dict:
    await request.app.state.audit.log("annotation", actor="human", text=body.text,
                                      kind=body.kind)
    return {"ok": True}
