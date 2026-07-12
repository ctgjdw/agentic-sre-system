from fastapi import FastAPI

from sre_gateway.api import health
from sre_gateway.settings import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="sre-gateway")
    app.state.settings = settings
    app.state.health = {}
    app.include_router(health.router, prefix="/api")
    return app
