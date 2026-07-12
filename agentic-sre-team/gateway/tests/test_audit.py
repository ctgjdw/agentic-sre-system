from sqlalchemy import select

from sre_gateway.audit import AuditWriter, get_flag, set_flag
from sre_gateway.db.models import AuditEvent, Case


async def _mk_case(db) -> str:
    async with db() as s:
        c = Case(display_id="CASE-0001", kind="incident", fingerprint="fp", thread_id="t1")
        s.add(c)
        await s.commit()
        return c.id


async def test_log_llm_increments_case_counters(db):
    case_id = await _mk_case(db)
    audit = AuditWriter(db)
    await audit.log_llm(case_id, node="triage", model_id="fake", tokens_in=100,
                        tokens_out=20, cost_usd=0.01, latency_ms=5,
                        prompt_hash="a", response_hash="b")
    async with db() as s:
        case = await s.get(Case, case_id)
        events = (await s.execute(select(AuditEvent))).scalars().all()
    assert case.tokens_in == 100 and case.tokens_out == 20
    assert round(case.spend_usd, 4) == 0.01
    assert events[0].event_type == "llm_call" and events[0].actor == "triage"


async def test_pause_flag_roundtrip_and_audited(db):
    audit = AuditWriter(db)
    assert await get_flag(db, "paused") is False
    await set_flag(db, "paused", True, actor="alex", audit=audit)
    assert await get_flag(db, "paused") is True
    async with db() as s:
        events = (await s.execute(select(AuditEvent))).scalars().all()
    assert any(e.event_type == "pause" for e in events)
