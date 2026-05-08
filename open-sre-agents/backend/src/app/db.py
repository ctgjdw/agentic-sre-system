from typing import Any

import asyncpg

# `app.state.pool` is the canonical home for the asyncpg pool.
# `get_pool` is a FastAPI dependency so tests can override it.

_pool: asyncpg.Pool | None = None


async def init_pool(database_url: str) -> asyncpg.Pool:
    global _pool
    _pool = await asyncpg.create_pool(database_url, min_size=1, max_size=5)
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool() -> Any:
    if _pool is None:
        raise RuntimeError("DB pool not initialised")
    return _pool
