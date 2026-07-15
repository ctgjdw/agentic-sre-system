"""The human-facing Telegram/channel messages must never leak internal identifiers
(thread UUIDs) or graph-node jargon. Operators still get the raw detail in halt_reason
and the SSE error frame; the chat surface stays readable."""
from sre_gateway.db.models import Case
from sre_gateway.graph.runner import CaseRunner


class _RaisingGraph:
    """Minimal graph stub whose astream fails the way a script-exhausted node does."""

    def astream(self, graph_input, cfg, stream_mode=None):
        async def _gen():
            raise RuntimeError("script exhausted for node 'triage'")
            yield  # pragma: no cover - makes this an async generator

        return _gen()


async def _seed_case(db, display_id: str) -> str:
    async with db() as s:
        case = Case(display_id=display_id, kind="incident", title="t",
                    fingerprint="fp", thread_id="")
        s.add(case)
        await s.flush()
        case.thread_id = case.id
        await s.commit()
        return case.id


async def test_runner_error_message_is_user_friendly(deps, db):
    case_id = await _seed_case(db, "CASE-9001")
    runner = CaseRunner(deps, _RaisingGraph())

    await runner._run(case_id, {"case_id": case_id})

    # The case is parked with the RAW detail preserved for the operator...
    async with db() as s:
        case = await s.get(Case, case_id)
    assert case.status == "needs_human"
    assert "triage" in (case.halt_reason or "")  # raw node kept for the console/audit

    # ...but the channel message names the case by its display id and hides the UUID +
    # the internal "node" wording.
    sent = deps.channel.sent[-1]["text"]
    assert "CASE-9001" in sent
    assert case_id not in sent
    assert "node" not in sent.lower()
    assert "needs a human" in sent.lower()


async def test_manual_park_message_uses_display_id(deps, db):
    case_id = await _seed_case(db, "CASE-9002")
    runner = CaseRunner(deps, _RaisingGraph())

    await runner.park(case_id, reason="on-call requested a closer look", actor="@alex")

    sent = deps.channel.sent[-1]["text"]
    assert "CASE-9002" in sent
    assert case_id not in sent
    assert "@alex" in sent
