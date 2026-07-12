from datetime import UTC, datetime, timedelta

from sre_gateway.audit import AuditWriter
from sre_gateway.db.models import Case, SignalRow
from sre_gateway.domain.signal import Signal
from sre_gateway.intake.noise import NoiseControl


def _sig(fp="grafana:abc", summary="s", labels=None) -> Signal:
    return Signal(source="grafana", fingerprint=fp, summary=summary, labels=labels or {})


async def _open_case(db, fp="grafana:abc", signal_age_s=300) -> str:
    async with db() as s:
        c = Case(display_id="CASE-0001", kind="incident", fingerprint=fp, thread_id="t")
        s.add(c)
        await s.flush()
        s.add(SignalRow(case_id=c.id, source="grafana", kind="incident", fingerprint=fp,
                        received_at=datetime.now(UTC) - timedelta(seconds=signal_age_s)))
        await s.commit()
        return c.id


async def test_new_fingerprint_opens(db):
    nc = NoiseControl(db, AuditWriter(db))
    d = await nc.decide(_sig())
    assert d.action == "open" and d.reason == "new"


async def test_same_fingerprint_attaches_as_dedup(db):
    case_id = await _open_case(db, signal_age_s=300)
    nc = NoiseControl(db, AuditWriter(db), debounce_s=60)
    d = await nc.decide(_sig())
    assert d.action == "attach" and d.case_id == case_id and d.reason == "dedup"


async def test_rapid_repeat_is_debounced(db):
    await _open_case(db, signal_age_s=5)
    nc = NoiseControl(db, AuditWriter(db), debounce_s=60)
    d = await nc.decide(_sig())
    assert d.action == "suppress" and d.reason == "debounce"


async def test_rapid_burst_is_labeled_burst(db):
    await _open_case(db, signal_age_s=5)
    nc = NoiseControl(db, AuditWriter(db), debounce_s=60, burst_n=3, burst_window_s=60)
    reasons = [(await nc.decide(_sig())).reason for _ in range(4)]
    assert reasons[:2] == ["debounce", "debounce"]  # decisions 1-2: below burst_n
    assert reasons[2:] == ["burst", "burst"]        # from the 3rd decision in the window


async def test_closed_cases_do_not_match(db):
    case_id = await _open_case(db)
    async with db() as s:
        (await s.get(Case, case_id)).status = "closed"
        await s.commit()
    nc = NoiseControl(db, AuditWriter(db))
    d = await nc.decide(_sig())
    assert d.action == "open"
