import asyncio
import logging
from collections import defaultdict
from datetime import UTC, datetime

from langgraph.types import Command
from sqlalchemy import func, select, update

from sre_gateway.db.models import Case, CaseEvent
from sre_gateway.graph.deps import GraphDeps

logger = logging.getLogger("sre.runner")


class CaseRunner:
    def __init__(self, deps: GraphDeps, graph) -> None:
        self.deps = deps
        self.graph = graph
        self.tasks: dict[str, asyncio.Task] = {}
        self.subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._seq: dict[str, int] = {}
        self._seq_locks: dict[str, asyncio.Lock] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def running_count(self) -> int:
        return sum(1 for t in self.tasks.values() if not t.done())

    def lock_for(self, case_id: str) -> asyncio.Lock:
        """Per-case mutex serializing start/resume/decision against this case's run."""
        return self._locks.setdefault(case_id, asyncio.Lock())

    def is_running(self, case_id: str) -> bool:
        task = self.tasks.get(case_id)
        return task is not None and not task.done()

    def subscribe(self, case_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self.subscribers[case_id].add(q)
        return q

    def unsubscribe(self, case_id: str, q: asyncio.Queue) -> None:
        self.subscribers[case_id].discard(q)

    async def start(self, case_id: str, initial: dict | None) -> None:
        async with self.lock_for(case_id):
            if initial is None:
                initial = await self._resolve_initial(case_id)
            self._launch(case_id, initial)

    async def resume(self, case_id: str, payload: dict) -> None:
        async with self.lock_for(case_id):
            self._launch(case_id, Command(resume=payload))

    def _launch(self, case_id: str, graph_input) -> None:
        """Spawn the background run. Caller must hold lock_for(case_id): this is where
        the double-decision / double-resume race (Important 3) is closed - the
        liveness check and the task creation happen as one atomic step under the lock,
        instead of apply_decision's separate read-then-act status check racing the
        gate's post-interrupt status flip."""
        if self.is_running(case_id):
            raise RuntimeError(f"case {case_id} already has an active run")
        self.tasks[case_id] = asyncio.create_task(self._run(case_id, graph_input))

    async def _resolve_initial(self, case_id: str) -> dict | None:
        # None means "resume from checkpoint", but a case whose thread was never
        # started (e.g. the process crashed between case-open and the first run) has
        # no checkpoint at all: None input then reaches triage with an empty state and
        # KeyErrors on case_id. Seed a fresh input in that case instead.
        cfg = {"configurable": {"thread_id": case_id}}
        state = await self.graph.aget_state(cfg)
        return None if state.values else {"case_id": case_id}

    async def park(self, case_id: str, reason: str, actor: str) -> None:
        task = self.tasks.get(case_id)
        if task and not task.done():
            task.cancel()
        async with self.deps.sessionmaker() as s:
            # Parked time is a human wait too: stamp waiting_since so a later resume
            # excludes it from the active-time wall-clock budget.
            await s.execute(update(Case).where(Case.id == case_id).values(
                status="needs_human", phase="parked", halt_reason=reason,
                waiting_since=datetime.now(UTC)))
            await s.commit()
        await self.deps.audit.log("budget", actor=actor, case_id=case_id, reason=reason,
                                  manual=True)
        await self._emit(case_id, "parked", {"reason": reason, "actor": actor})
        await self.deps.channel.send(f"Case {case_id} escalated to human by {actor}: {reason}")

    async def relaunch_open_cases(self) -> None:
        async with self.deps.sessionmaker() as s:
            ids = (await s.execute(select(Case.id).where(Case.status == "open"))
                   ).scalars().all()
        for case_id in ids:
            await self.start(case_id, None)  # resume from checkpoint

    async def _next_seq(self, case_id: str) -> int:
        if case_id not in self._seq:
            # Two concurrent _emits for a case whose seq counter isn't cached yet would
            # otherwise both read MAX(seq) and install the same base, then both hand out
            # the same next seq - a collision on the unique (case_id, seq) index that
            # parks the case. Guard just the first-init read-and-install with a lock;
            # once cached, the += below has no await point so it can't interleave.
            lock = self._seq_locks.setdefault(case_id, asyncio.Lock())
            async with lock:
                if case_id not in self._seq:
                    async with self.deps.sessionmaker() as s:
                        current = (await s.execute(
                            select(func.max(CaseEvent.seq))
                            .where(CaseEvent.case_id == case_id))).scalar_one() or 0
                    self._seq[case_id] = current
        self._seq[case_id] += 1
        return self._seq[case_id]

    async def emit(self, case_id: str, type_: str, payload: dict) -> None:
        """Public entry point for callers outside the graph run loop (REST endpoints)."""
        await self._emit(case_id, type_, payload)

    async def _emit(self, case_id: str, type_: str, payload: dict,
                    persist: bool = True) -> None:
        event = {"type": type_, **payload}
        if persist:
            seq = await self._next_seq(case_id)
            event["seq"] = seq
            async with self.deps.sessionmaker() as s:
                s.add(CaseEvent(case_id=case_id, seq=seq, type=type_, payload=payload))
                await s.commit()
        for q in list(self.subscribers[case_id]):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                self.subscribers[case_id].discard(q)

    async def _run(self, case_id: str, graph_input) -> None:
        cfg = {"configurable": {"thread_id": case_id}}
        try:
            async for mode, chunk in self.graph.astream(
                    graph_input, cfg, stream_mode=["updates", "custom", "messages"]):
                if mode == "custom":
                    payload = dict(chunk)
                    await self._emit(case_id, payload.pop("type", "custom"), payload)
                elif mode == "messages":
                    msg, meta = chunk
                    text = getattr(msg, "content", "")
                    if text:
                        await self._emit(case_id, "token",
                                         {"node": meta.get("langgraph_node", ""),
                                          "text": str(text)[:500]}, persist=False)
                elif mode == "updates":
                    if "__interrupt__" in chunk:
                        intr = chunk["__interrupt__"][0]
                        value = getattr(intr, "value", {}) or {}
                        await self._emit(case_id, "gate_waiting", dict(value))
                        gate = value.get("gate", "rca")
                        await self.deps.channel.send(
                            f"{value.get('display_id', case_id)}: {gate} ready for "
                            f"review (artifact v{value.get('version')}). Approve in the "
                            f"console or right here.",
                            buttons=[
                                {"text": "Approve", "data": f"dec:{case_id}:{gate}:approve"},
                                {"text": "Reject", "data": f"dec:{case_id}:{gate}:reject"},
                            ])
                    else:
                        for node, node_update in chunk.items():
                            keys = sorted(node_update or {})
                            await self._emit(case_id, "node_update",
                                             {"node": node, "keys": keys})
            await self._emit(case_id, "run_idle", {})
        except asyncio.CancelledError:
            raise
        except Exception as err:
            logger.exception("case %s runner failed", case_id)
            async with self.deps.sessionmaker() as s:
                await s.execute(update(Case).where(Case.id == case_id).values(
                    status="needs_human", phase="parked",
                    halt_reason=f"runner error: {err}"[:500]))
                await s.commit()
            await self._emit(case_id, "error", {"error": str(err)[:500]})
            await self.deps.channel.send(f"Case {case_id} parked on error: {err}")

    async def stop(self) -> None:
        # Cancel AND await every still-running task before callers tear down the
        # checkpointer/engine: a bare cancel() leaves the task pending past shutdown
        # ("Task was destroyed but it is pending"), and it may still touch the DB after
        # the caller assumes it's safe to dispose. _run re-raises CancelledError, so
        # gather(return_exceptions=True) absorbs it cleanly.
        tasks = [t for t in self.tasks.values() if not t.done()]
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
