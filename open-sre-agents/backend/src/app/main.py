from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
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
