import asyncio
import json
import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import desc, select
from sse_starlette import EventSourceResponse

from sre_gateway.db.models import (
    Approval, Artifact, Case, CaseEvent, EvidenceRow, Hypothesis, SignalRow,
)
from sre_gateway.graph.decisions import apply_decision

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
        hypotheses = (await s.execute(
            select(Hypothesis).where(Hypothesis.case_id == case_id)
            .order_by(Hypothesis.hid)
        )).scalars().all()
        evidence = (await s.execute(
            select(EvidenceRow).where(EvidenceRow.case_id == case_id)
            .order_by(EvidenceRow.eid)
        )).scalars().all()
        artifacts = (await s.execute(
            select(Artifact).where(Artifact.case_id == case_id)
            .order_by(Artifact.kind, Artifact.version)
        )).scalars().all()
        approvals = (await s.execute(
            select(Approval).where(Approval.case_id == case_id)
            .order_by(Approval.decided_at)
        )).scalars().all()
    return {
        "case": case_json(case),
        "signals": [
            {"id": x.id, "source": x.source, "reporter": x.reporter, "summary": x.summary,
             "fingerprint": x.fingerprint, "labels": x.labels, "is_primary": x.is_primary,
             "attach_reason": x.attach_reason, "received_at": x.received_at.isoformat()}
            for x in signals
        ],
        "hypotheses": [
            {"hid": h.hid, "statement": h.statement, "status": h.status,
             "confidence": h.confidence, "evidence_for": h.evidence_for,
             "evidence_against": h.evidence_against, "round": h.round,
             "updated_at": h.updated_at.isoformat()}
            for h in hypotheses
        ],
        "evidence": [
            {"eid": e.eid, "worker": e.worker, "toolset": e.toolset,
             "invocation": e.invocation, "excerpt": e.excerpt,
             "source_url": e.source_url, "observed_at": e.observed_at.isoformat(),
             "hypothesis_links": e.hypothesis_links}
            for e in evidence
        ],
        "artifacts": [
            {"kind": a.kind, "version": a.version, "structured": a.structured,
             "body_md": a.body_md, "body_edited_md": a.body_edited_md,
             "verification": a.verification, "model_id": a.model_id,
             "created_at": a.created_at.isoformat()}
            for a in artifacts
        ],
        "approvals": [
            {"gate": ap.gate, "decision": ap.decision, "decided_by": ap.decided_by,
             "channel": ap.channel, "annotation": ap.annotation, "diff": ap.diff,
             "decided_at": ap.decided_at.isoformat()}
            for ap in approvals
        ],
    }


@router.get("/cases/{case_id}/stream")
async def stream_case(request: Request, case_id: str, last_event_id: int | None = None):
    runner = request.app.state.runner
    last = last_event_id or int(request.headers.get("Last-Event-ID", 0) or 0)

    async def gen():
        q = runner.subscribe(case_id)
        try:
            async with request.app.state.sessionmaker() as s:
                # Replay ALL persisted events in seq order: a `.limit(200)` here would
                # silently drop everything past it for a client reconnecting without a
                # Last-Event-ID on a long-running case.
                stmt = (select(CaseEvent).where(CaseEvent.case_id == case_id)
                        .order_by(CaseEvent.seq))
                if last:
                    stmt = stmt.where(CaseEvent.seq > last)
                replayed = last
                for row in (await s.execute(stmt)).scalars():
                    replayed = max(replayed, row.seq)
                    yield {"id": str(row.seq), "event": row.type,
                           "data": json.dumps(row.payload)}
            while True:
                # The run is a background task, not a long-lived connection: once it's
                # idle (parked at a gate, closed, or errored) there's nothing left to
                # relay, so close the stream rather than block forever. The client
                # reconnects with Last-Event-ID for the next run (approval, retry, ...).
                task = runner.tasks.get(case_id)
                active = task is not None and not task.done()
                try:
                    event = await asyncio.wait_for(q.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    if not active:
                        break
                    continue
                seq = event.get("seq")
                if seq is not None and seq <= replayed:
                    continue  # already sent in replay (subscribe-before-replay race)
                yield {"id": str(seq or ""), "event": event["type"],
                       "data": json.dumps({k: v for k, v in event.items()
                                           if k not in ("type", "seq")})}
        finally:
            runner.unsubscribe(case_id, q)

    return EventSourceResponse(gen(), ping=15)


class DecisionBody(BaseModel):
    gate: str
    decision: Literal["approve", "approve_with_edits", "reject"]
    decided_by: str
    channel: str = "ui"
    edited_body_md: str | None = None
    annotation: str = ""


@router.post("/cases/{case_id}/decision")
async def decide_case(request: Request, case_id: str, body: DecisionBody) -> dict:
    await apply_decision(request.app.state.sessionmaker, request.app.state.runner, case_id,
                         body.gate, decision=body.decision, decided_by=body.decided_by,
                         channel=body.channel, edited_body_md=body.edited_body_md,
                         annotation=body.annotation)
    return {"ok": True}


class ParkBody(BaseModel):
    reason: str
    actor: str


@router.post("/cases/{case_id}/park")
async def park_case(request: Request, case_id: str, body: ParkBody) -> dict:
    await request.app.state.runner.park(case_id, body.reason, body.actor)
    return {"ok": True}


class ResumeBody(BaseModel):
    actor: str


@router.post("/cases/{case_id}/resume")
async def resume_case(request: Request, case_id: str, body: ResumeBody) -> dict:
    sm = request.app.state.sessionmaker
    runner = request.app.state.runner
    # Graph parks run park -> END, so the thread is COMPLETE, not interrupted: a plain
    # ainvoke(None) on it re-drives nothing. Instead start a fresh, non-None run that
    # re-enters from START (a parked case gets re-triaged) - verified empirically on
    # langgraph 1.2.9 that a fresh input on a completed thread restarts execution.
    # "halt": None is required in that input: guarded() only ever *sets* halt on a
    # breach, it's never cleared on success, so the persisted breach would otherwise
    # make every router's _halted() check true forever and re-park immediately.
    async with runner.lock_for(case_id):
        async with sm() as s:
            case = await s.get(Case, case_id)
        if case is None:
            raise HTTPException(404)
        if case.status != "needs_human":
            raise HTTPException(409, detail=f"case is {case.status}, not needs_human")
        async with sm() as s:
            case = await s.get(Case, case_id)
            case.status, case.halt_reason = "open", None
            # Parked time doesn't count against the wall-clock budget: credit it to
            # waited_seconds now that the human wait is over, same as a gate resume.
            if case.waiting_since is not None:
                case.waited_seconds += int(
                    (datetime.now(UTC) - case.waiting_since).total_seconds())
                case.waiting_since = None
            await s.commit()
        await request.app.state.audit.log("budget", actor=body.actor, case_id=case_id,
                                          manual=True, action="resume")
        try:
            runner._launch(case_id, {"case_id": case_id, "halt": None})
        except RuntimeError as err:
            raise HTTPException(409, detail=str(err)) from err
    return {"ok": True}


class ContextBody(BaseModel):
    text: str
    author: str


@router.post("/cases/{case_id}/context")
async def add_context(request: Request, case_id: str, body: ContextBody) -> dict:
    sm = request.app.state.sessionmaker
    async with sm() as s:
        case = await s.get(Case, case_id)
        if case is None:
            raise HTTPException(404)
        s.add(SignalRow(case_id=case_id, source="human_api", kind=case.kind,
                        fingerprint=f"human-context:{case_id}:{uuid.uuid4()}",
                        summary=body.text, reporter=body.author, is_primary=False,
                        attach_reason="human_context"))
        await s.commit()
    await request.app.state.audit.log("intake", actor=body.author, case_id=case_id,
                                      reason="human_context")
    await request.app.state.runner.emit(case_id, "context_added",
                                        {"text": body.text, "author": body.author})
    return {"ok": True}
