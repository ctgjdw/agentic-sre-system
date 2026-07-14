from sqlalchemy import update

from sre_gateway.db.models import Case
from sre_gateway.graph.deps import GraphDeps, stream_writer
from sre_gateway.graph.routers import fan_out


def make_plan(deps: GraphDeps):
    async def plan(state: dict) -> dict:
        writer = stream_writer()
        this_round = state.get("round", 0) + 1
        workers = [s.node for s in fan_out({**state, "round": this_round})]
        async with deps.sessionmaker() as s:
            await s.execute(update(Case).where(Case.id == state["case_id"])
                            .values(round=this_round))
            await s.commit()
        writer({"type": "plan", "workers": workers,
                "effort": state.get("effort", "medium"), "round": this_round})
        return {"round": this_round, "need_more": False,
                "worker_reports": [], "evidence": []}

    return plan
