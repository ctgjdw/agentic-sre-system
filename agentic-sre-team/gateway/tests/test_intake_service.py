from sqlalchemy import select

from sre_gateway.audit import AuditWriter, set_flag
from sre_gateway.db.models import Case, SignalRow
from sre_gateway.domain.signal import Signal
from sre_gateway.intake.noise import NoiseControl
from sre_gateway.intake.service import IntakeService


def _svc(db, opened):
    audit = AuditWriter(db)

    async def on_opened(case_id: str) -> None:
        opened.append(case_id)

    return IntakeService(db, audit, NoiseControl(db, audit), on_case_opened=on_opened)


async def test_open_creates_case_signal_and_display_id(db):
    opened: list[str] = []
    svc = _svc(db, opened)
    res = await svc.ingest(Signal(source="grafana", fingerprint="grafana:a", summary="s1"))
    assert res.action == "open" and res.display_id == "CASE-0001"
    assert opened == [res.case_id]
    async with db() as s:
        case = await s.get(Case, res.case_id)
        sigs = (await s.execute(select(SignalRow))).scalars().all()
    assert case.title == "s1" and case.thread_id == case.id
    assert len(sigs) == 1 and sigs[0].is_primary


async def test_attach_adds_signal_row_without_new_case(db):
    opened: list[str] = []
    svc = _svc(db, opened)
    first = await svc.ingest(Signal(source="grafana", fingerprint="grafana:a", summary="s1"))
    # age the first signal past debounce
    async with db() as s:
        row = (await s.execute(select(SignalRow))).scalars().one()
        from datetime import UTC, datetime, timedelta
        row.received_at = datetime.now(UTC) - timedelta(seconds=300)
        await s.commit()
    res = await svc.ingest(Signal(source="grafana", fingerprint="grafana:a", summary="s2"))
    assert res.action == "attach" and res.case_id == first.case_id
    assert len(opened) == 1


async def test_paused_suppresses_everything(db):
    opened: list[str] = []
    svc = _svc(db, opened)
    await set_flag(db, "paused", True, actor="t", audit=AuditWriter(db))
    res = await svc.ingest(Signal(source="grafana", fingerprint="grafana:z", summary="s"))
    assert res.action == "suppress" and opened == []
