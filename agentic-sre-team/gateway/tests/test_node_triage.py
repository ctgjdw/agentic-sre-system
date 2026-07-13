from sqlalchemy import select

from sre_gateway.db.models import Case, Hypothesis, SignalRow
from sre_gateway.graph.nodes.triage import make_triage


async def _seed_case(db) -> Case:
    async with db() as s:
        c = Case(display_id="CASE-0001", kind="incident", fingerprint="grafana:x",
                 thread_id="t", title="raw alert")
        s.add(c)
        await s.flush()
        s.add(SignalRow(case_id=c.id, source="grafana", kind="incident",
                        fingerprint="grafana:x", is_primary=True,
                        summary="Error rate spike on admin-server /api/v1/users",
                        labels={"service": "admin-server"}))
        await s.commit()
        return c


async def test_triage_seeds_board_and_acks(deps, db):
    case = await _seed_case(db)
    node = make_triage(deps)
    update = await node({"case_id": case.id, "kind": "incident"})
    assert update["severity"] == 2 and update["effort"] == "medium"
    assert [h["hid"] for h in update["hypotheses"]] == ["H1", "H2", "H3", "H4"]
    assert update["round"] == 0 and update["query_hints"] == []
    async with db() as s:
        rows = (await s.execute(select(Hypothesis))).scalars().all()
        refreshed = await s.get(Case, case.id)
    assert len(rows) == 4 and refreshed.severity == 2
    assert deps.channel.sent and "CASE-0001" in deps.channel.sent[0]["text"]
