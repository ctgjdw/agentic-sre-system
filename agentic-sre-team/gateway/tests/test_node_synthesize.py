from sqlalchemy import select

from sre_gateway.db.models import Case, Hypothesis
from sre_gateway.graph.nodes.synthesize import make_synthesize


async def _seed(db):
    async with db() as s:
        c = Case(display_id="CASE-0001", kind="incident", fingerprint="f", thread_id="t",
                 severity=3, title="p95 climbing")
        s.add(c)
        await s.flush()
        for i, stmt in enumerate(["pool exhaustion", "n+1 admin api", "cpu", "kong"], 1):
            s.add(Hypothesis(case_id=c.id, hid=f"H{i}", statement=stmt, round=0))
        await s.commit()
        return c


async def test_synthesize_updates_board_and_posts_status(deps, db):
    case = await _seed(db)
    node = make_synthesize(deps)
    state = {"case_id": case.id, "severity": 3, "round": 1,
             "hypotheses": [{"hid": f"H{i}", "statement": s, "status": "open",
                             "confidence": 0.25}
                            for i, s in enumerate(["pool", "n+1", "cpu", "kong"], 1)],
             "worker_reports": [{"worker": "metrics", "summary": "5xx up",
                                 "findings": [], "degraded": False}],
             "evidence": [{"eid": "E1", "excerpt": "5xx 18%"}]}
    update = await node(state)
    assert update["need_more"] is False
    board = {h["hid"]: h for h in update["hypotheses"]}
    assert board["H2"]["status"] == "supported" and board["H3"]["status"] == "refuted"
    async with db() as s:
        h2 = (await s.execute(select(Hypothesis).where(Hypothesis.hid == "H2"))).scalar_one()
    assert h2.status == "supported" and abs(h2.confidence - 0.78) < 1e-6
    assert any("0.78" in m["text"] or "N+1" in m["text"] for m in deps.channel.sent)
