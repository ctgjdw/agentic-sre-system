from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from sre_gateway.db.models import Case, SignalRow
from sre_gateway.domain.signal import Signal


class GroupingRule(BaseModel):
    name: str
    label_keys: list[str]


class GroupingConfig(BaseModel):
    window_seconds: int = 120
    rules: list[GroupingRule] = []


def load_grouping(path: Path) -> GroupingConfig:
    return GroupingConfig.model_validate(yaml.safe_load(path.read_text()) or {})


class CorrelationGrouping:
    def __init__(self, config: GroupingConfig) -> None:
        self.config = config

    async def find_group_match(self, session: AsyncSession, signal: Signal) -> str | None:
        cutoff = datetime.now(UTC) - timedelta(seconds=self.config.window_seconds)
        for rule in self.config.rules:
            values = {k: signal.labels.get(k) for k in rule.label_keys}
            if any(v is None for v in values.values()):
                continue
            recent = (await session.execute(
                select(SignalRow).join(Case, Case.id == SignalRow.case_id)
                .where(Case.status != "closed",
                       SignalRow.kind == signal.kind.value,  # never group across case kinds
                       SignalRow.received_at >= cutoff)
                .order_by(desc(SignalRow.received_at)).limit(200)
            )).scalars().all()
            for row in recent:
                if all(row.labels.get(k) == v for k, v in values.items()):
                    return row.case_id
        return None
