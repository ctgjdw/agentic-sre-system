from fastapi.testclient import TestClient

from app.main import app


def test_health_returns_ok():
    # TestClient without `with` skips lifespan, so DB pool init does not run.
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_cors_allows_configured_origin():
    # Module already imported; we reload to pick up the new env var if needed,
    # but for this smoke we just confirm the middleware echoes Access-Control-Allow-Origin.
    client = TestClient(app)
    response = client.get(
        "/health",
        headers={"Origin": "http://example.com", "Access-Control-Request-Method": "GET"},
    )
    assert response.status_code == 200
    assert "access-control-allow-origin" in {k.lower() for k in response.headers.keys()}
