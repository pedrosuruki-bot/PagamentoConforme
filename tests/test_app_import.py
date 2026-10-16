from fastapi.testclient import TestClient

from app.main import app


def test_application_health_and_public_landing():
    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"

        landing = client.get("/")
        assert landing.status_code == 200
        assert "PagamentoConforme" in landing.text
        assert "/signup" in landing.text
