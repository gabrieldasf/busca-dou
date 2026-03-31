"""Tests for web dashboard routes."""

from httpx import ASGITransport, AsyncClient

from src.app.main import app


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


async def test_detail_422_invalid_uuid() -> None:
    """GET /pub/{not-a-uuid} should return 422."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/pub/not-a-uuid")
    assert resp.status_code == 422
