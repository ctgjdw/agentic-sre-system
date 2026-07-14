from datetime import UTC, datetime
from pathlib import Path

import yaml
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sre_gateway.db.models import Case


class CaseBudget(BaseModel):
    tokens: int = 500_000
    tool_calls: int = 60
    wall_clock_s: int = 900


def load_budgets(path: Path) -> CaseBudget:
    data = yaml.safe_load(path.read_text()) or {}
    return CaseBudget.model_validate(data.get("case", {}))


class BudgetEnforcer:
    def __init__(self, sm: async_sessionmaker[AsyncSession], budget: CaseBudget) -> None:
        self._sm = sm
        self.budget = budget

    async def check_case(self, case_id: str) -> str | None:
        async with self._sm() as s:
            case = await s.get(Case, case_id)
        if case is None:
            return None
        total_tokens = case.tokens_in + case.tokens_out
        if total_tokens > self.budget.tokens:
            return f"tokens {total_tokens}/{self.budget.tokens}"
        if case.tool_calls > self.budget.tool_calls:
            return f"tool_calls {case.tool_calls}/{self.budget.tool_calls}"
        # Exclude time spent waiting on a human (gate review, parked escalation): only
        # active graph run time counts against the wall-clock budget.
        active_age = (datetime.now(UTC) - case.created_at).total_seconds() \
            - case.waited_seconds
        if active_age > self.budget.wall_clock_s:
            return f"wall_clock {int(active_age)}s/{self.budget.wall_clock_s}s"
        return None

    async def agent_spend_today(self, agent: str) -> float:
        async with self._sm() as s:
            res = await s.execute(text(
                "SELECT COALESCE(SUM((payload->>'cost_usd')::float), 0) FROM audit_events "
                "WHERE actor = :actor AND event_type = 'llm_call' "
                "AND ts >= date_trunc('day', now() AT TIME ZONE 'utc') AT TIME ZONE 'utc'"
            ), {"actor": agent})
            return float(res.scalar_one())

    async def check_agent(self, agent: str, usd_per_day: float) -> str | None:
        spend = await self.agent_spend_today(agent)
        if spend >= usd_per_day:
            return f"usd_per_day {spend:.2f}/{usd_per_day:.2f}"
        return None
