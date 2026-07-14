from fastapi import HTTPException

from sre_gateway.db.models import Case


async def apply_decision(sessionmaker, runner, case_id: str, gate: str, *,
                         decision: str, decided_by: str, channel: str = "ui",
                         edited_body_md: str | None = None, annotation: str = "") -> None:
    async with sessionmaker() as s:
        case = await s.get(Case, case_id)
    if case is None:
        raise HTTPException(404)
    if case.status != "waiting_approval" or case.phase != f"gate_{gate}":
        raise HTTPException(409, detail=f"case is at {case.phase} ({case.status}), "
                                        f"not waiting on gate_{gate}")
    await runner.resume(case_id, {"decision": decision, "decided_by": decided_by,
                                  "channel": channel, "edited_body_md": edited_body_md,
                                  "annotation": annotation})
