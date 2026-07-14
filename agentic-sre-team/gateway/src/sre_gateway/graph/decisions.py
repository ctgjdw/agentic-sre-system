from fastapi import HTTPException
from langgraph.types import Command

from sre_gateway.db.models import Case


async def apply_decision(sessionmaker, runner, case_id: str, gate: str, *,
                         decision: str, decided_by: str, channel: str = "ui",
                         edited_body_md: str | None = None, annotation: str = "") -> None:
    # The status check and the resume must be atomic: the gate only flips status back
    # to "open" deep inside the resumed run's post-interrupt code, not synchronously
    # here, so two decisions fired close together (double-clicked Approve, or UI +
    # Telegram at once) would otherwise both read "waiting_approval" and both resume
    # the same thread concurrently. Hold the per-case lock across both steps and use
    # the lock-assuming _launch directly (runner.resume() re-acquires the same lock).
    async with runner.lock_for(case_id):
        async with sessionmaker() as s:
            case = await s.get(Case, case_id)
        if case is None:
            raise HTTPException(404)
        if case.status != "waiting_approval" or case.phase != f"gate_{gate}":
            raise HTTPException(409, detail=f"case is at {case.phase} ({case.status}), "
                                            f"not waiting on gate_{gate}")
        try:
            runner._launch(case_id, Command(resume={
                "decision": decision, "decided_by": decided_by, "channel": channel,
                "edited_body_md": edited_body_md, "annotation": annotation}))
        except RuntimeError as err:
            raise HTTPException(409, detail=str(err)) from err
