from dataclasses import dataclass
from typing import Awaitable, Callable

from sqlalchemy import desc, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sre_gateway.audit import AuditWriter, get_flag
from sre_gateway.db.models import Case, SignalRow
from sre_gateway.domain.signal import Signal
from sre_gateway.intake.noise import IntakeDecision, NoiseControl


@dataclass
class IngestResult:
    action: str
    case_id: str | None
    display_id: str | None


class IntakeService:
    def __init__(self, sm: async_sessionmaker[AsyncSession], audit: AuditWriter,
                 noise: NoiseControl,
                 on_case_opened: Callable[[str], Awaitable[None]] | None = None) -> None:
        self._sm = sm
        self._audit = audit
        self._noise = noise
        self.on_case_opened = on_case_opened

    async def ingest(self, signal: Signal) -> IngestResult:
        if await get_flag(self._sm, "paused"):
            await self._audit.log("suppression", actor="noise-control",
                                  fingerprint=signal.fingerprint, reason="paused")
            return IngestResult("suppress", None, None)

        decision: IntakeDecision = await self._noise.decide(signal)
        if decision.action == "suppress":
            return IngestResult("suppress", decision.case_id, None)
        if decision.action == "attach":
            async with self._sm() as s:
                s.add(self._row(signal, decision.case_id, primary=False,
                                reason=decision.reason))
                await s.commit()
            return IngestResult("attach", decision.case_id, None)

        try:
            async with self._sm() as s:
                seq = (await s.execute(text("SELECT nextval('case_display_seq')"))).scalar_one()
                case = Case(display_id=f"CASE-{seq:04d}", kind=signal.kind.value,
                            title=signal.summary, fingerprint=signal.fingerprint, thread_id="")
                s.add(case)
                await s.flush()
                # id is a Python-side default resolved during flush, so thread_id (= case id)
                # can only be assigned once the row has been flushed and case.id is populated.
                case.thread_id = case.id
                s.add(self._row(signal, case.id, primary=True, reason="opened"))
                await s.commit()
                case_id, display_id = case.id, case.display_id
        except IntegrityError:
            # A concurrent ingest for this brand-new fingerprint won the race and already
            # opened a case (partial unique index on cases.fingerprint WHERE status <>
            # 'closed'). Attach this signal to that case instead of failing or double-opening.
            async with self._sm() as s:
                existing = (await s.execute(
                    select(Case).where(Case.fingerprint == signal.fingerprint,
                                       Case.status != "closed")
                    .order_by(desc(Case.created_at)).limit(1)
                )).scalar_one()
                s.add(self._row(signal, existing.id, primary=False, reason="dedup"))
                await s.commit()
                existing_id = existing.id
            # The decision was "open" (NoiseControl logs nothing for that), so this race-driven
            # attach would otherwise be unaudited; log it to match the normal attach path.
            await self._audit.log("intake", actor="intake", case_id=existing_id,
                                  fingerprint=signal.fingerprint, reason="dedup",
                                  source=signal.source.value)
            return IngestResult("attach", existing_id, None)

        await self._audit.log("intake", actor="intake", case_id=case_id,
                              fingerprint=signal.fingerprint, reason="opened",
                              source=signal.source.value)
        if self.on_case_opened is not None:
            await self.on_case_opened(case_id)
        return IngestResult("open", case_id, display_id)

    @staticmethod
    def _row(signal: Signal, case_id: str, *, primary: bool, reason: str) -> SignalRow:
        return SignalRow(case_id=case_id, source=signal.source.value,
                         reporter=signal.reporter, kind=signal.kind.value,
                         fingerprint=signal.fingerprint, summary=signal.summary,
                         labels=signal.labels, payload=signal.payload,
                         is_primary=primary, attach_reason=reason,
                         received_at=signal.received_at)
