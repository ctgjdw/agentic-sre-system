from fastapi.testclient import TestClient

from app.main import app


def test_health_returns_ok():
    # TestClient without `with` skips lifespan, so DB pool init does not run.
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
