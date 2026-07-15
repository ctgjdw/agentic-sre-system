from dataclasses import dataclass

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sre_gateway.audit import AuditWriter, get_flag
from sre_gateway.budget import BudgetEnforcer
from sre_gateway.channels.base import Channel
from sre_gateway.db.models import Case
from sre_gateway.environment import EnvironmentConfig
from sre_gateway.graph.grafana_links import LinkBuilder
from sre_gateway.holmes.client import HolmesClient
from sre_gateway.llm.factory import ModelFactory
from sre_gateway.manifests import AgentManifest
from sre_gateway.settings import Settings


@dataclass
class GraphDeps:
    settings: Settings
    sessionmaker: async_sessionmaker[AsyncSession]
    audit: AuditWriter
    models: ModelFactory
    manifests: dict[str, AgentManifest]
    budget: BudgetEnforcer
    holmes: HolmesClient
    channel: Channel
    environment: EnvironmentConfig
    links: LinkBuilder | None = None


def stream_writer():
    try:
        from langgraph.config import get_stream_writer

        return get_stream_writer()
    except RuntimeError:
        return lambda _event: None


def guarded(deps: GraphDeps, name: str, fn):
    """Between-nodes governance: pause + budget checks run before every node."""

    async def wrapped(state: dict):
        writer = stream_writer()
        case_id = state.get("case_id", "")
        if await get_flag(deps.sessionmaker, "paused"):
            return {"halt": {"reason": "paused", "at_node": name}}
        breach = await deps.budget.check_case(case_id)
        if breach:
            await deps.audit.log("budget", actor=name, case_id=case_id, breach=breach)
            return {"halt": {"reason": f"budget: {breach}", "at_node": name}}
        async with deps.sessionmaker() as s:
            await s.execute(update(Case).where(Case.id == case_id).values(phase=name))
            await s.commit()
        writer({"type": "node_start", "node": name})
        result = await fn(state)
        writer({"type": "node_end", "node": name})
        return result

    return wrapped
