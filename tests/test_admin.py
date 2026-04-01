"""Tests for admin backfill endpoint."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from src.api.v1.deps import get_api_key, hash_api_key
from src.app.database import get_session
from src.app.main import app

client = TestClient(app)

TEST_API_KEY = "test-admin-key-12345"
TEST_KEY_HASH = hash_api_key(TEST_API_KEY)


def _mock_api_key() -> AsyncMock:
    key = AsyncMock()
    key.id = uuid.uuid4()
    key.key_hash = TEST_KEY_HASH
    key.name = "Test Admin Key"
    key.tier = "free"
    key.is_active = True
    key.rate_limit = 100
    key.last_used_at = None
    return key


def test_backfill_rejects_without_api_key() -> None:
    resp = client.post("/api/v1/admin/backfill-embeddings")
    assert resp.status_code in (401, 403)


def test_backfill_succeeds_with_valid_key() -> None:
    mock_key = _mock_api_key()

    async def fake_get_api_key() -> AsyncMock:
        return mock_key

    # Mock a publication without embedding
    mock_pub = MagicMock()
    mock_pub.id = uuid.uuid4()
    mock_pub.body = "Test publication body content"
    mock_pub.embedding = None

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [mock_pub]
    mock_session.execute.return_value = mock_result

    async def fake_session():
        yield mock_session

    app.dependency_overrides[get_api_key] = fake_get_api_key
    app.dependency_overrides[get_session] = fake_session

    try:
        with patch("src.api.v1.routes.admin.generate_embedding") as mock_embed:
            mock_embed.return_value = [0.1] * 1536

            resp = client.post(
                "/api/v1/admin/backfill-embeddings",
                headers={"X-API-Key": TEST_API_KEY},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["total"] == 1
            assert data["updated"] == 1
            assert data["failed"] == 0
            mock_embed.assert_called_once_with("Test publication body content")
    finally:
        app.dependency_overrides.pop(get_api_key, None)
        app.dependency_overrides.pop(get_session, None)


def test_backfill_handles_embedding_failure() -> None:
    mock_key = _mock_api_key()

    async def fake_get_api_key() -> AsyncMock:
        return mock_key

    mock_pub = MagicMock()
    mock_pub.id = uuid.uuid4()
    mock_pub.body = "Test body"
    mock_pub.embedding = None

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [mock_pub]
    mock_session.execute.return_value = mock_result

    async def fake_session():
        yield mock_session

    app.dependency_overrides[get_api_key] = fake_get_api_key
    app.dependency_overrides[get_session] = fake_session

    try:
        with patch("src.api.v1.routes.admin.generate_embedding") as mock_embed:
            mock_embed.side_effect = RuntimeError("API down")

            resp = client.post(
                "/api/v1/admin/backfill-embeddings",
                headers={"X-API-Key": TEST_API_KEY},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["total"] == 1
            assert data["updated"] == 0
            assert data["failed"] == 1
    finally:
        app.dependency_overrides.pop(get_api_key, None)
        app.dependency_overrides.pop(get_session, None)
