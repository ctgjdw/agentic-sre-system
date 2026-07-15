from sre_gateway.settings import Settings


async def test_healthz_ok(client):
    res = await client.get("/api/healthz")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["service"] == "sre-gateway"
    assert body["components"] == {"db": "ok", "grafana_poller": "disabled"}


def test_settings_env_prefix(monkeypatch):
    monkeypatch.setenv("SRE_ENV_NAME", "unit-test")
    s = Settings(database_url="postgresql+asyncpg://x:x@localhost:1/x")
    assert s.env_name == "unit-test"
