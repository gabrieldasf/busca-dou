"""Web dashboard routes - serves HTML via Jinja2 + HTMX."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.database import get_session
from src.models.publication import Publication

logger = logging.getLogger(__name__)

templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

router = APIRouter(tags=["web"])


@router.get("/", response_class=HTMLResponse)
async def search_page(request: Request) -> HTMLResponse:
    """Render the search page (initial load, no results)."""
    return templates.TemplateResponse(
        request, "search.html", {"publications": None, "q": None}
    )


@router.get("/search-results", response_class=HTMLResponse)
async def search_results(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    q: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    organ: str | None = None,
    section: str | None = None,
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
) -> HTMLResponse:
    """Return search results as HTML partial (for HTMX)."""
    from datetime import date as date_type

    from src.api.v1.schemas import decode_cursor, encode_cursor

    stmt = select(
        Publication.id,
        Publication.title,
        Publication.section,
        Publication.organ,
        Publication.act_type,
        Publication.published_at,
        Publication.page_number,
        Publication.pdf_url,
    )

    if q:
        tsquery = func.plainto_tsquery(literal_column("'portuguese'"), q)
        stmt = stmt.add_columns(
            func.ts_headline(
                literal_column("'portuguese'"),
                Publication.body,
                tsquery,
                literal_column("'StartSel=<mark>, StopSel=</mark>, MaxWords=60, MinWords=20'"),
            ).label("snippet"),
            func.ts_rank(Publication.body_tsv, tsquery).label("relevance"),
        )
        stmt = stmt.where(Publication.body_tsv.op("@@")(tsquery))
    else:
        stmt = stmt.add_columns(
            literal_column("NULL").label("snippet"),
            literal_column("NULL").label("relevance"),
        )

    if date_from:
        stmt = stmt.where(Publication.published_at >= date_type.fromisoformat(date_from))
    if date_to:
        stmt = stmt.where(Publication.published_at <= date_type.fromisoformat(date_to))
    if organ:
        stmt = stmt.where(Publication.organ == organ)
    if section:
        stmt = stmt.where(Publication.section == section)

    if cursor:
        from sqlalchemy import tuple_

        cursor_date, cursor_id = decode_cursor(cursor)
        stmt = stmt.where(
            tuple_(Publication.published_at, Publication.id) < tuple_(cursor_date, cursor_id)
        )

    # Count total (without pagination) for display
    count_stmt = select(func.count()).select_from(Publication)
    if q:
        tsquery_count = func.plainto_tsquery(literal_column("'portuguese'"), q)
        count_stmt = count_stmt.where(Publication.body_tsv.op("@@")(tsquery_count))
    if date_from:
        count_stmt = count_stmt.where(
            Publication.published_at >= date_type.fromisoformat(date_from)
        )
    if date_to:
        count_stmt = count_stmt.where(Publication.published_at <= date_type.fromisoformat(date_to))
    if organ:
        count_stmt = count_stmt.where(Publication.organ == organ)
    if section:
        count_stmt = count_stmt.where(Publication.section == section)

    count_result = await session.execute(count_stmt)
    total = count_result.scalar() or 0

    stmt = stmt.order_by(Publication.published_at.desc(), Publication.id.desc())
    stmt = stmt.limit(limit + 1)

    result = await session.execute(stmt)
    rows = list(result.all())

    has_more = len(rows) > limit
    if has_more:
        rows = rows[:limit]

    next_cursor = None
    if has_more and rows:
        last = rows[-1]
        next_cursor = encode_cursor(last.published_at, last.id)

    return templates.TemplateResponse(
        request,
        "partials/results.html",
        {"publications": rows, "total": total, "q": q, "next_cursor": next_cursor},
    )


@router.get("/pub/{publication_id}", response_class=HTMLResponse)
async def publication_detail(
    publication_id: uuid.UUID,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HTMLResponse:
    """Render publication detail page."""
    stmt = select(Publication).where(Publication.id == publication_id)
    result = await session.execute(stmt)
    pub = result.scalar_one_or_none()

    if pub is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Publicacao nao encontrada")

    return templates.TemplateResponse(request, "detail.html", {"pub": pub})
