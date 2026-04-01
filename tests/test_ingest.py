"""Tests for ingest endpoint authentication."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from src.api.v1.deps import get_api_key, hash_api_key
from src.app.database import get_session
from src.app.main import app

client = TestClient(app)

TEST_API_KEY = "test-ingest-key-12345"
TEST_KEY_HASH = hash_api_key(TEST_API_KEY)


def _mock_api_key() -> AsyncMock:
    key = AsyncMock()
    key.id = uuid.uuid4()
    key.key_hash = TEST_KEY_HASH
    key.name = "Test Ingest Key"
    key.tier = "free"
    key.is_active = True
    key.rate_limit = 100
    key.last_used_at = None
    return key


def _headers() -> dict[str, str]:
    return {"X-API-Key": TEST_API_KEY}


# --- Auth rejection tests ---


def test_ingest_rejects_without_api_key() -> None:
    resp = client.post("/api/v1/ingest", json={"date": "2026-03-30"})
    assert resp.status_code in (401, 403)


def test_reingest_rejects_without_api_key() -> None:
    resp = client.post("/api/v1/ingest/reingest", json={"date": "2026-03-30"})
    assert resp.status_code in (401, 403)


# --- Auth success tests ---


def test_ingest_succeeds_with_valid_key() -> None:
    mock_key = _mock_api_key()

    async def fake_get_api_key() -> AsyncMock:
        return mock_key

    async def fake_session():
        yield AsyncMock()

    app.dependency_overrides[get_api_key] = fake_get_api_key
    app.dependency_overrides[get_session] = fake_session

    try:
        with patch("src.api.v1.routes.ingest.IngestionService") as mock_service:
            instance = AsyncMock()
            instance.ingest_edition.return_value = 5
            mock_service.return_value = instance

            resp = client.post(
                "/api/v1/ingest",
                json={"date": "2026-03-30"},
                headers=_headers(),
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["publications_count"] == 5
            assert data["status"] == "completed"
    finally:
        app.dependency_overrides.pop(get_api_key, None)
        app.dependency_overrides.pop(get_session, None)


def test_reingest_succeeds_with_valid_key() -> None:
    mock_key = _mock_api_key()

    async def fake_get_api_key() -> AsyncMock:
        return mock_key

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.rowcount = 2
    mock_session.execute.return_value = mock_result

    async def fake_session():
        yield mock_session

    app.dependency_overrides[get_api_key] = fake_get_api_key
    app.dependency_overrides[get_session] = fake_session

    try:
        with patch("src.api.v1.routes.ingest.IngestionService") as mock_service:
            instance = AsyncMock()
            instance.ingest_edition.return_value = 3
            mock_service.return_value = instance

            resp = client.post(
                "/api/v1/ingest/reingest",
                json={"date": "2026-03-30"},
                headers=_headers(),
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["publications_count"] == 3
            assert data["status"] == "reingested"
    finally:
        app.dependency_overrides.pop(get_api_key, None)
        app.dependency_overrides.pop(get_session, None)
