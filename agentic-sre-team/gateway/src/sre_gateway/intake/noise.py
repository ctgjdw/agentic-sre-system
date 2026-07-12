from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sre_gateway.audit import AuditWriter
from sre_gateway.db.models import AuditEvent, Case, SignalRow
from sre_gateway.domain.signal import Signal


@dataclass
class IntakeDecision:
    action: Literal["open", "attach", "suppress"]
    case_id: str | None
    reason: str


class GroupingEngine(Protocol):
    async def find_group_match(self, session: AsyncSession, signal: Signal) -> str | None: ...


class NoiseControl:
    def __init__(self, sm: async_sessionmaker[AsyncSession], audit: AuditWriter, *,
                 dedup_window_s: int = 1800, debounce_s: int = 60,
                 burst_n: int = 5, burst_window_s: int = 60,
                 grouping: GroupingEngine | None = None) -> None:
        self._sm = sm
        self._audit = audit
        self.dedup_window_s = dedup_window_s
        self.debounce_s = debounce_s
        self.burst_n = burst_n
        self.burst_window_s = burst_window_s
        self.grouping = grouping

    async def decide(self, signal: Signal) -> IntakeDecision:
        now = datetime.now(UTC)
        async with self._sm() as s:
            open_case = (await s.execute(
                select(Case).where(Case.fingerprint == signal.fingerprint,
                                   Case.status != "closed")
                .order_by(desc(Case.created_at)).limit(1)
            )).scalar_one_or_none()
            if open_case:
                last = (await s.execute(
                    select(SignalRow.received_at)
                    .where(SignalRow.case_id == open_case.id,
                           SignalRow.fingerprint == signal.fingerprint)
                    .order_by(desc(SignalRow.received_at)).limit(1)
                )).scalar_one_or_none()
                if last and now - last < timedelta(seconds=self.debounce_s):
                    prior = (await s.execute(
                        select(func.count(AuditEvent.id)).where(
                            AuditEvent.ts >= now - timedelta(seconds=self.burst_window_s),
                            AuditEvent.payload["fingerprint"].astext
                            == signal.fingerprint))).scalar_one()
                    reason = "burst" if prior + 1 >= self.burst_n else "debounce"
                    decision = IntakeDecision("suppress", open_case.id, reason)
                else:
                    decision = IntakeDecision("attach", open_case.id, "dedup")
            elif self.grouping and (gid := await self.grouping.find_group_match(s, signal)):
                decision = IntakeDecision("attach", gid, "grouped")
            else:
                decision = IntakeDecision("open", None, "new")

        if decision.action == "suppress":
            await self._audit.log("suppression", actor="noise-control",
                                  case_id=decision.case_id,
                                  fingerprint=signal.fingerprint, reason=decision.reason)
        elif decision.action == "attach":
            await self._audit.log("intake", actor="noise-control", case_id=decision.case_id,
                                  fingerprint=signal.fingerprint, reason=decision.reason)
        return decision
