import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from sre_gateway.audit import AuditWriter, set_flag
from sre_gateway.db.models import AuditEvent, Case, SignalRow
from sre_gateway.domain.signal import Signal
from sre_gateway.intake.noise import IntakeDecision, NoiseControl
from sre_gateway.intake.service import IngestResult, IntakeService


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


async def test_db_rejects_second_open_case_same_fingerprint(db):
    async with db() as s:
        s.add(Case(display_id="CASE-0001", kind="incident", fingerprint="fp-dup", thread_id="t1"))
        await s.commit()
    async with db() as s:
        s.add(Case(display_id="CASE-0002", kind="incident", fingerprint="fp-dup", thread_id="t2"))
        with pytest.raises(IntegrityError, match="ix_cases_fingerprint_open"):
            await s.commit()


async def test_new_open_case_allowed_after_prior_case_closes(db):
    async with db() as s:
        first = Case(display_id="CASE-0001", kind="incident",
                     fingerprint="fp-recur", thread_id="t1")
        s.add(first)
        await s.commit()
        first_id = first.id

    async with db() as s:
        case = await s.get(Case, first_id)
        case.status = "closed"
        await s.commit()

    async with db() as s:
        # same fingerprint as the now-closed case above: the partial WHERE excludes it,
        # so this second, non-closed case must be allowed.
        s.add(Case(display_id="CASE-0002", kind="incident",
                   fingerprint="fp-recur", thread_id="t2"))
        await s.commit()


async def test_race_on_create_attaches_to_the_case_that_won(db):
    async with db() as s:
        winner = Case(display_id="CASE-0001", kind="incident",
                      fingerprint="grafana:race", thread_id="t1")
        s.add(winner)
        await s.commit()
        winner_id = winner.id

    class _AlwaysOpenNoise:
        """Minimal stub forcing IntakeService.ingest down the case-create path, so the
        create collides with the pre-existing open case for the same fingerprint."""

        async def decide(self, signal: Signal) -> IntakeDecision:
            return IntakeDecision("open", None, "new")

    opened: list[str] = []

    async def on_opened(case_id: str) -> None:
        opened.append(case_id)

    svc = IntakeService(db, AuditWriter(db), _AlwaysOpenNoise(), on_case_opened=on_opened)
    res = await svc.ingest(Signal(source="grafana", fingerprint="grafana:race", summary="dup"))

    assert res == IngestResult("attach", winner_id, None)
    assert opened == []  # on_case_opened must not fire on the race/attach path
    async with db() as s:
        rows = (await s.execute(
            select(SignalRow).where(SignalRow.case_id == winner_id)
        )).scalars().all()
        events = (await s.execute(
            select(AuditEvent).where(AuditEvent.case_id == winner_id,
                                     AuditEvent.event_type == "intake")
        )).scalars().all()
    assert len(rows) == 1
    assert rows[0].is_primary is False and rows[0].attach_reason == "dedup"
    # the race-driven attach must still be audited, like the normal attach path
    assert len(events) == 1 and events[0].payload["reason"] == "dedup"
