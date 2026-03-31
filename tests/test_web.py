"""Tests for web dashboard routes."""

from unittest.mock import AsyncMock, MagicMock

from httpx import ASGITransport, AsyncClient

from src.app.database import get_session
from src.app.main import app


def _mock_session() -> AsyncMock:
    """Create a mock async session that returns empty results for dropdown queries."""
    session = AsyncMock()
    result = MagicMock()
    result.all.return_value = []
    session.execute.return_value = result
    return session


async def _override_get_session():
    yield _mock_session()


app.dependency_overrides[get_session] = _override_get_session


async def test_search_page_returns_html() -> None:
    """GET / should return the search page HTML."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "BuscaDOU" in resp.text
    assert "Busca em Diarios Oficiais" in resp.text
    assert "htmx" in resp.text


async def test_search_page_has_form_elements() -> None:
    """Search page should contain the HTMX search form."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/")
    assert 'hx-get="/search-results"' in resp.text
    assert 'name="q"' in resp.text


async def test_search_page_has_filter_dropdowns() -> None:
    """Search page should contain filter dropdowns for organ, section, act_type."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/")
    assert 'name="organ"' in resp.text
    assert 'name="section"' in resp.text
    assert 'name="act_type"' in resp.text
    assert "Todos os orgaos" in resp.text
    assert "Todas as secoes" in resp.text
    assert "Todos os tipos" in resp.text


async def test_search_page_has_date_chips() -> None:
    """Search page should contain date shortcut chips."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/")
    assert "Hoje" in resp.text
    assert "Ultima semana" in resp.text
    assert "Ultimo mes" in resp.text


async def test_detail_422_invalid_uuid() -> None:
    """GET /pub/{not-a-uuid} should return 422."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/pub/not-a-uuid")
    assert resp.status_code == 422
