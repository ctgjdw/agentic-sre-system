from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sre_gateway.db.models import CaseLearning, Runbook

Embedder = "Callable[[list[str]], Awaitable[list[list[float]]]]"


async def index_runbook(sm: async_sessionmaker[AsyncSession], embed, *, title: str,
                        body_md: str, source_case_id: str | None, tags: list) -> str:
    vec = (await embed([f"{title}\n{body_md[:2000]}"]))[0]
    async with sm() as s:
        row = Runbook(title=title, body_md=body_md, source_case_id=source_case_id,
                      tags=tags, embedding=vec)
        s.add(row)
        await s.commit()
        return row.id


async def search_runbooks(sm, embed, query: str, k: int = 3) -> list[dict]:
    vec = (await embed([query]))[0]
    async with sm() as s:
        rows = (await s.execute(
            select(Runbook).order_by(Runbook.embedding.cosine_distance(vec)).limit(k)
        )).scalars().all()
    return [{"id": r.id, "title": r.title, "snippet": r.body_md[:400]} for r in rows]


async def index_learning(sm, embed, *, case_id: str, signal_signature: str,
                         confirmed_root_cause: str, decisive_queries: list,
                         false_leads: list) -> str:
    vec = (await embed([signal_signature]))[0]
    async with sm() as s:
        row = CaseLearning(case_id=case_id, signal_signature=signal_signature,
                           confirmed_root_cause=confirmed_root_cause,
                           decisive_queries=decisive_queries, false_leads=false_leads,
                           embedding=vec)
        s.add(row)
        await s.commit()
        return row.id


async def search_learnings(sm, embed, query: str, k: int = 3) -> list[dict]:
    vec = (await embed([query]))[0]
    async with sm() as s:
        rows = (await s.execute(
            select(CaseLearning).order_by(CaseLearning.embedding.cosine_distance(vec)).limit(k)
        )).scalars().all()
    return [{"signal_signature": r.signal_signature,
             "confirmed_root_cause": r.confirmed_root_cause,
             "decisive_queries": r.decisive_queries} for r in rows]
