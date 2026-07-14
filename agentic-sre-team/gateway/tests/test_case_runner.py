import asyncio

from sre_gateway.db.models import Case, SignalRow
from sre_gateway.graph import make_checkpointer
from sre_gateway.graph.build import build_graph
from sre_gateway.graph.runner import CaseRunner


async def test_next_seq_concurrent_first_init_never_collides(deps, db):
    # Before any event has been persisted for a case, _next_seq's cold-cache path reads
    # MAX(seq) from the DB (a real await point) before installing the base. Many
    # concurrent first calls for the same fresh case must still hand out distinct,
    # gapless sequence numbers, not race each other into the same base.
    runner = CaseRunner(deps, graph=None)
    case_id = "concurrent-seq-case"
    seqs = await asyncio.gather(*[runner._next_seq(case_id) for _ in range(20)])
    assert sorted(seqs) == list(range(1, 21))


async def _seed(db):
    async with db() as s:
        c = Case(display_id="CASE-0001", kind="incident", fingerprint="grafana:x",
                 thread_id="", title="raw alert")
        s.add(c)
        await s.flush()
        c.thread_id = c.id
        s.add(SignalRow(case_id=c.id, source="grafana", kind="incident", is_primary=True,
                        fingerprint="grafana:x", summary="Error rate spike",
                        labels={}))
        await s.commit()
        return c


async def test_resolve_initial_seeds_case_id_when_thread_never_started(deps, db, pg_url):
    # None means "resume from checkpoint", but a case whose thread was never started
    # (e.g. the process crashed between case-open and the first run) has no checkpoint
    # at all: relaunch_open_cases()/start(case_id, None) on it must not hand the graph a
    # bare None, which reaches triage with an empty state and KeyErrors on case_id.
    case = await _seed(db)
    async with make_checkpointer(pg_url) as saver:
        graph = build_graph(deps, saver)
        runner = CaseRunner(deps, graph)
        assert await runner._resolve_initial(case.id) == {"case_id": case.id}

        cfg = {"configurable": {"thread_id": case.id}}
        await graph.ainvoke({"case_id": case.id, "kind": "incident"}, cfg)
        # Once a checkpoint exists, None is left alone: real resume-from-checkpoint.
        assert await runner._resolve_initial(case.id) is None
