from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver


@asynccontextmanager
async def make_checkpointer(database_url: str):
    conninfo = database_url.replace("postgresql+asyncpg", "postgresql")
    async with AsyncPostgresSaver.from_conn_string(conninfo) as saver:
        await saver.setup()
        yield saver
