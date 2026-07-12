from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sre_gateway.db.models import AuditEvent, Case, Setting


class AuditWriter:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sm = sessionmaker

    async def log(self, event_type: str, actor: str, case_id: str | None = None, **payload) -> None:
        async with self._sm() as s:
            s.add(AuditEvent(event_type=event_type, actor=actor, case_id=case_id, payload=payload))
            await s.commit()

    async def log_llm(self, case_id: str | None, *, node: str, model_id: str, tokens_in: int,
                      tokens_out: int, cost_usd: float, latency_ms: int,
                      prompt_hash: str, response_hash: str) -> None:
        async with self._sm() as s:
            s.add(AuditEvent(event_type="llm_call", actor=node, case_id=case_id, payload={
                "model_id": model_id, "tokens_in": tokens_in, "tokens_out": tokens_out,
                "cost_usd": cost_usd, "latency_ms": latency_ms,
                "prompt_hash": prompt_hash, "response_hash": response_hash,
            }))
            if case_id:
                await s.execute(update(Case).where(Case.id == case_id).values(
                    tokens_in=Case.tokens_in + tokens_in,
                    tokens_out=Case.tokens_out + tokens_out,
                    spend_usd=Case.spend_usd + cost_usd,
                ))
            await s.commit()

    async def log_tool(self, case_id: str | None, *, worker: str, toolset: str,
                       invocation: str, latency_ms: int = 0) -> None:
        async with self._sm() as s:
            s.add(AuditEvent(event_type="tool_call", actor=worker, case_id=case_id, payload={
                "toolset": toolset, "invocation": invocation[:2000], "latency_ms": latency_ms,
            }))
            if case_id:
                await s.execute(update(Case).where(Case.id == case_id)
                                .values(tool_calls=Case.tool_calls + 1))
            await s.commit()


async def get_flag(sm: async_sessionmaker[AsyncSession], key: str, default: bool = False) -> bool:
    async with sm() as s:
        row = await s.get(Setting, key)
        return bool(row.value.get("enabled", default)) if row else default


async def set_flag(sm: async_sessionmaker[AsyncSession], key: str, value: bool,
                   actor: str, audit: AuditWriter) -> None:
    async with sm() as s:
        row = await s.get(Setting, key)
        if row is None:
            s.add(Setting(key=key, value={"enabled": value}))
        else:
            row.value = {"enabled": value}
        await s.commit()
    await audit.log("pause", actor=actor, key=key, enabled=value)
