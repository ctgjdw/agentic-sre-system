from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from sre_gateway.api import cases, health, webhooks
from sre_gateway.audit import AuditWriter
from sre_gateway.db.engine import make_engine, make_sessionmaker
from sre_gateway.intake.grouping import CorrelationGrouping, load_grouping
from sre_gateway.intake.noise import NoiseControl
from sre_gateway.intake.service import IntakeService
from sre_gateway.settings import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = make_engine(settings.database_url)
        app.state.engine = engine
        app.state.sessionmaker = make_sessionmaker(engine)
        app.state.audit = AuditWriter(app.state.sessionmaker)
        grouping = CorrelationGrouping(load_grouping(settings.config_dir / "grouping.yaml"))
        noise = NoiseControl(app.state.sessionmaker, app.state.audit, grouping=grouping)
        app.state.intake = IntakeService(app.state.sessionmaker, app.state.audit, noise)
        try:
            async with app.state.sessionmaker() as s:
                await s.execute(text("SELECT 1"))
            app.state.health["db"] = "ok"
        except Exception:
            # A down DB should surface as degraded health at request time, not a boot failure.
            app.state.health["db"] = "degraded"
        yield
        await engine.dispose()

    app = FastAPI(title="sre-gateway", lifespan=lifespan)
    app.state.settings = settings
    app.state.health = {}
    app.include_router(health.router, prefix="/api")
    app.include_router(webhooks.router, prefix="/api")
    app.include_router(cases.router, prefix="/api")
    return app
