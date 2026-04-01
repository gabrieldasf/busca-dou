"""Tests for authentication system."""

from __future__ import annotations

from unittest.mock import AsyncMock

from httpx import ASGITransport, AsyncClient

from src.app.database import get_session
from src.app.main import app
from src.services.auth import (
    create_session_token,
    decode_session_token,
    hash_password,
    verify_password,
)

# --- Password hashing ---


def test_hash_and_verify_password() -> None:
    hashed = hash_password("testpassword123")
    assert verify_password("testpassword123", hashed)
    assert not verify_password("wrongpassword", hashed)


def test_hash_is_unique() -> None:
    h1 = hash_password("same_password")
    h2 = hash_password("same_password")
    assert h1 != h2  # bcrypt salts should differ


# --- Session tokens ---


def test_session_token_roundtrip() -> None:
    import uuid

    user_id = uuid.uuid4()
    token = create_session_token(user_id)
    decoded = decode_session_token(token)
    assert decoded == user_id


def test_session_token_invalid() -> None:
    assert decode_session_token("garbage") is None
    assert decode_session_token("") is None


# --- Login page ---


async def test_login_page_renders() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/login")
    assert resp.status_code == 200
    assert "Entrar" in resp.text


async def test_signup_page_renders() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/signup")
    assert resp.status_code == 200
    assert "Criar conta" in resp.text


# --- Dashboard redirect ---


async def test_dashboard_redirects_without_session() -> None:
    mock_session = AsyncMock()

    async def fake_session():
        yield mock_session

    app.dependency_overrides[get_session] = fake_session
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test", follow_redirects=False
        ) as client:
            resp = await client.get("/dashboard")
        assert resp.status_code == 302
        assert "/login" in resp.headers.get("location", "")
    finally:
        app.dependency_overrides.pop(get_session, None)
