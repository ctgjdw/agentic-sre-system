from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from testcontainers.postgres import PostgresContainer

from sre_gateway.api.app import create_app
from sre_gateway.db.engine import make_engine, make_sessionmaker
from sre_gateway.db.models import Base
from sre_gateway.settings import Settings


def run_migrations(sync_url: str) -> None:
    cfg = Config("alembic.ini")
    cfg.set_main_option("script_location", "alembic")
    import os

    os.environ["SRE_DATABASE_URL"] = sync_url.replace("+psycopg", "+asyncpg")
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session")
def pg_url() -> str:
    with PostgresContainer("pgvector/pgvector:pg16", driver="psycopg") as pg:
        sync_url = pg.get_connection_url()
        run_migrations(sync_url)
        yield sync_url.replace("+psycopg", "+asyncpg")


@pytest.fixture
async def db(pg_url):
    engine = make_engine(pg_url)
    async with engine.begin() as conn:
        # settings table is preserved config-free; wipe every domain table between tests
        tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
        await conn.execute(text("ALTER SEQUENCE case_display_seq RESTART WITH 1"))
    yield make_sessionmaker(engine)
    await engine.dispose()


@pytest.fixture
async def client(pg_url):
    settings = Settings(database_url=pg_url, grafana_webhook_secret="topsecret",
                        config_dir=Path(__file__).parents[2] / "config")
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as c:
            yield c
