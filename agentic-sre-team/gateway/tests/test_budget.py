from datetime import UTC, datetime, timedelta
from pathlib import Path

from sre_gateway.audit import AuditWriter
from sre_gateway.budget import BudgetEnforcer, load_budgets
from sre_gateway.db.models import Case

CONFIG = Path(__file__).parents[2] / "config/budgets.yaml"


async def _case(db, **kw) -> str:
    async with db() as s:
        c = Case(display_id="CASE-0001", kind="incident", fingerprint="f", thread_id="t", **kw)
        s.add(c)
        await s.commit()
        return c.id


async def test_within_budget_returns_none(db):
    case_id = await _case(db)
    enforcer = BudgetEnforcer(db, load_budgets(CONFIG))
    assert await enforcer.check_case(case_id) is None


async def test_token_breach(db):
    case_id = await _case(db, tokens_in=400_000, tokens_out=200_000)
    enforcer = BudgetEnforcer(db, load_budgets(CONFIG))
    breach = await enforcer.check_case(case_id)
    assert breach and breach.startswith("tokens")


async def test_wall_clock_breach(db):
    case_id = await _case(db)
    async with db() as s:
        (await s.get(Case, case_id)).created_at = datetime.now(UTC) - timedelta(seconds=2000)
        await s.commit()
    enforcer = BudgetEnforcer(db, load_budgets(CONFIG))
    breach = await enforcer.check_case(case_id)
    assert breach and breach.startswith("wall_clock")


async def test_agent_daily_spend_and_cap(db):
    audit = AuditWriter(db)
    await audit.log_llm(None, node="rca", model_id="m", tokens_in=1, tokens_out=1,
                        cost_usd=4.20, latency_ms=1, prompt_hash="a", response_hash="b")
    enforcer = BudgetEnforcer(db, load_budgets(CONFIG))
    assert abs(await enforcer.agent_spend_today("rca") - 4.20) < 1e-6
    assert await enforcer.check_agent("rca", usd_per_day=6.0) is None
    breach = await enforcer.check_agent("rca", usd_per_day=4.0)
    assert breach and "usd_per_day" in breach
