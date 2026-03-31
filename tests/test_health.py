from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from src.app.main import app

client = TestClient(app)


def test_health_endpoint_returns_ok() -> None:
    with patch("src.app.main.engine") as mock_engine:
        mock_conn = AsyncMock()
        mock_engine.connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_engine.connect.return_value.__aexit__ = AsyncMock(return_value=False)

        response = client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["version"] == "0.1.0"
    assert "timestamp" in data
