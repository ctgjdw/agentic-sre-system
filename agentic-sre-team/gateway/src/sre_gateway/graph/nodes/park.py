from datetime import UTC, datetime

from sqlalchemy import update

from sre_gateway.db.models import Case
from sre_gateway.graph.deps import GraphDeps


def make_park(deps: GraphDeps):
    async def park(state: dict) -> dict:
        case_id = state["case_id"]
        halt = state.get("halt") or {"reason": "manual escalation", "at_node": "unknown"}
        async with deps.sessionmaker() as s:
            # Parked time is a human wait too: stamp waiting_since so a later resume
            # excludes it from the active-time wall-clock budget.
            await s.execute(update(Case).where(Case.id == case_id).values(
                status="needs_human", phase="parked", halt_reason=halt["reason"],
                waiting_since=datetime.now(UTC)))
            await s.commit()
        await deps.audit.log("budget", actor="park", case_id=case_id, **halt)
        await deps.channel.send(
            f"{state.get('display_id', case_id)} parked (needs human): {halt['reason']}. "
            f"Everything gathered so far is preserved; resume from the console.")
        return {}

    return park
