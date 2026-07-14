from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from testcontainers.postgres import PostgresContainer

from sre_gateway.api.app import create_app
from sre_gateway.audit import AuditWriter
from sre_gateway.budget import BudgetEnforcer, load_budgets
from sre_gateway.channels.log import LogChannel
from sre_gateway.db.engine import make_engine, make_sessionmaker
from sre_gateway.db.models import Base
from sre_gateway.environment import load_environment
from sre_gateway.graph.deps import GraphDeps
from sre_gateway.holmes.client import HolmesClient
from sre_gateway.llm.factory import ModelFactory, load_models_config
from sre_gateway.llm.scripted import reset_scripts
from sre_gateway.manifests import load_manifests
from sre_gateway.settings import Settings
from sre_gateway.testing import fake_holmes

# Shared by every graph-node test fixture (deps, and later deps_two_rounds /
# pipeline_deps / chat_service): the repo root holding config/, and this node's
# script fixture directory for the ScriptedChatModel fake profile.
ROOT = Path(__file__).parents[2]
SCRIPTS = Path(__file__).parent / "fixtures/scripts/incident_error_storm"
SCRIPTS_TWO_ROUNDS = Path(__file__).parent / "fixtures/scripts/incident_two_rounds"


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
async def client(db, pg_url):
    # Depending on `db` (not just `pg_url`) forces the TRUNCATE + case_display_seq reset to
    # run BEFORE the app lifespan starts, so relaunch_open_cases() at startup never picks up
    # a stale open case from a previous test's background run, and display_ids are
    # deterministic (CASE-0001).
    reset_scripts()
    settings = Settings(database_url=pg_url, grafana_webhook_secret="topsecret",
                        config_dir=ROOT / "config", models_profile="fake",
                        fake_script_dir=SCRIPTS)
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        holmes_http = AsyncClient(transport=ASGITransport(app=fake_holmes.app),
                                  base_url="http://holmes")
        app.state.deps.holmes = HolmesClient("http://holmes", client=holmes_http)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as c:
            yield c
        await holmes_http.aclose()


@pytest.fixture
async def deps(db, pg_url) -> GraphDeps:
    reset_scripts()
    settings = Settings(database_url=pg_url, config_dir=ROOT / "config")
    transport = ASGITransport(app=fake_holmes.app)
    async with AsyncClient(transport=transport, base_url="http://holmes") as holmes_http:
        yield GraphDeps(
            settings=settings, sessionmaker=db, audit=AuditWriter(db),
            models=ModelFactory(load_models_config(ROOT / "config/models.fake.yaml"),
                                script_dir=SCRIPTS),
            manifests=load_manifests(ROOT / "config/agents"),
            budget=BudgetEnforcer(db, load_budgets(ROOT / "config/budgets.yaml")),
            holmes=HolmesClient("http://holmes", client=holmes_http), channel=LogChannel(),
            environment=load_environment(ROOT / "config/environment.yaml"))


@pytest.fixture
async def deps_two_rounds(db, pg_url) -> GraphDeps:
    reset_scripts()
    settings = Settings(database_url=pg_url, config_dir=ROOT / "config")
    transport = ASGITransport(app=fake_holmes.app)
    async with AsyncClient(transport=transport, base_url="http://holmes") as holmes_http:
        yield GraphDeps(
            settings=settings, sessionmaker=db, audit=AuditWriter(db),
            models=ModelFactory(load_models_config(ROOT / "config/models.fake.yaml"),
                                script_dir=SCRIPTS_TWO_ROUNDS),
            manifests=load_manifests(ROOT / "config/agents"),
            budget=BudgetEnforcer(db, load_budgets(ROOT / "config/budgets.yaml")),
            holmes=HolmesClient("http://holmes", client=holmes_http), channel=LogChannel(),
            environment=load_environment(ROOT / "config/environment.yaml"))
