from fastapi.testclient import TestClient

from sre_gateway.api.app import create_app
from sre_gateway.settings import Settings


def _client() -> TestClient:
    app = create_app(Settings(database_url="postgresql+asyncpg://x:x@localhost:1/x"))
    return TestClient(app)


def test_healthz_ok():
    with _client() as client:
        res = client.get("/api/healthz")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["service"] == "sre-gateway"
    assert isinstance(body["components"], dict)


def test_settings_env_prefix(monkeypatch):
    monkeypatch.setenv("SRE_ENV_NAME", "unit-test")
    s = Settings(database_url="postgresql+asyncpg://x:x@localhost:1/x")
    assert s.env_name == "unit-test"
