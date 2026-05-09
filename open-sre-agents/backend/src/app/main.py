from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .db import close_pool, get_pool, init_pool
from .settings import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_pool(settings.database_url)
    try:
        yield
    finally:
        await close_pool()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.cors_origin],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/posts")
async def posts(limit: int = 50, pool=Depends(get_pool)) -> dict:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, author, content, likes, created_at "
            "FROM posts ORDER BY created_at DESC LIMIT $1",
            limit,
        )
    return {"posts": [dict(r) for r in rows]}


@app.get("/posts/search")
async def posts_search(q: str, limit: int = 50, pool=Depends(get_pool)) -> dict:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, author, content, likes, created_at "
            "FROM posts WHERE content ILIKE $1",
            f"%{q}%",
        )
    needle = q.lower()
    scored: list[tuple[int, dict]] = []
    for r in rows:
        haystack = r["content"].lower()
        count = 0
        pos = 0
        while True:
            pos = haystack.find(needle, pos)
            if pos == -1:
                break
            count += 1
            pos += 1
        scored.append((count, dict(r)))
    scored.sort(key=lambda t: t[0], reverse=True)
    return {"posts": [post for _, post in scored[:limit]]}


@app.get("/posts/{post_id}")
async def post_by_id(post_id: int, pool=Depends(get_pool)) -> dict:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, author, content, likes, created_at "
            "FROM posts WHERE id = $1",
            post_id,
        )
    if row is None:
        raise HTTPException(status_code=404, detail="post not found")
    return dict(row)
