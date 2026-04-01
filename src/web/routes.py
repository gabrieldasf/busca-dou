"""Web dashboard routes - serves HTML via Jinja2 + HTMX."""

from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path
from typing import Annotated

import markupsafe
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.config import settings
from src.app.database import get_session
from src.models.publication import Publication

logger = logging.getLogger(__name__)

templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


def _nl2p(text: str) -> markupsafe.Markup:
    """Convert double newlines to paragraphs, single newlines to <br>."""
    if not text:
        return markupsafe.Markup("")
    paragraphs = re.split(r'\n\s*\n', text)
    html_parts = []
    for p in paragraphs:
        p = p.strip()
        if p:
            escaped = markupsafe.escape(p)
            escaped = escaped.replace('\n', markupsafe.Markup('<br>'))
            html_parts.append(markupsafe.Markup(f'<p>{escaped}</p>'))  # noqa: S704
    return markupsafe.Markup('\n'.join(html_parts))  # noqa: S704


templates.env.filters['nl2p'] = _nl2p

router = APIRouter(tags=["web"])


@router.get("/", response_class=HTMLResponse)
async def search_page(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HTMLResponse:
    """Render the search page (initial load, no results)."""
    organs_result = await session.execute(
        select(Publication.organ).where(Publication.organ.is_not(None)).distinct().order_by(Publication.organ)
    )
    sections_result = await session.execute(
        select(Publication.section).where(Publication.section.is_not(None)).distinct().order_by(Publication.section)
    )
    act_types_result = await session.execute(
        select(Publication.act_type).where(Publication.act_type.is_not(None)).distinct().order_by(Publication.act_type)
    )

    # Fetch 5 most recent publications for empty state
    recent_result = await session.execute(
        select(
            Publication.id,
            Publication.title,
            Publication.organ,
            Publication.section,
            Publication.act_type,
            Publication.published_at,
        )
        .order_by(Publication.published_at.desc(), Publication.id.desc())
        .limit(5)
    )
    recent_publications = list(recent_result.all())

    return templates.TemplateResponse(
        request, "search.html", {
            "publications": None,
            "q": None,
            "recent_publications": recent_publications,
            "organs": [r[0] for r in organs_result.all()],
            "sections": [r[0] for r in sections_result.all()],
            "act_types": [r[0] for r in act_types_result.all()],
        }
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
    act_type: str | None = None,
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
) -> HTMLResponse:
    """Return search results as HTML partial (for HTMX)."""
    from datetime import date as date_type

    from sqlalchemy.types import Float

    from src.api.v1.schemas import decode_cursor, encode_cursor
    from src.services.ai import generate_embedding

    # Generate query embedding for semantic search
    query_embedding: list[float] | None = None
    if q and settings.openrouter_api_key:
        try:
            query_embedding = await generate_embedding(q)
        except Exception:
            logger.warning("Embedding generation failed, falling back to keyword search")

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
        from sqlalchemy import case, cast

        tsquery = func.plainto_tsquery(literal_column("'portuguese'"), q)
        keyword_rank = func.ts_rank(Publication.body_tsv, tsquery)

        stmt = stmt.add_columns(
            func.ts_headline(
                literal_column("'portuguese'"),
                Publication.body,
                tsquery,
                literal_column("'StartSel=<mark>, StopSel=</mark>, MaxWords=60, MinWords=20'"),
            ).label("snippet"),
        )
        stmt = stmt.where(Publication.body_tsv.op("@@")(tsquery))

        if query_embedding is not None:
            semantic_score = case(
                (
                    Publication.embedding.is_not(None),
                    cast(1 - Publication.embedding.cosine_distance(query_embedding), Float),
                ),
                else_=literal_column("0"),
            )
            hybrid_rank = 0.7 * keyword_rank + 0.3 * semantic_score
            stmt = stmt.add_columns(hybrid_rank.label("relevance"))
        else:
            stmt = stmt.add_columns(keyword_rank.label("relevance"))
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
    if act_type:
        stmt = stmt.where(Publication.act_type == act_type)

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
    if act_type:
        count_stmt = count_stmt.where(Publication.act_type == act_type)

    count_result = await session.execute(count_stmt)
    total = count_result.scalar() or 0

    if q:
        stmt = stmt.order_by(literal_column("relevance").desc().nulls_last(), Publication.id.desc())
    else:
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

    organs_result = await session.execute(
        select(Publication.organ).where(Publication.organ.is_not(None)).distinct().order_by(Publication.organ)
    )
    sections_result = await session.execute(
        select(Publication.section).where(Publication.section.is_not(None)).distinct().order_by(Publication.section)
    )
    act_types_result = await session.execute(
        select(Publication.act_type).where(Publication.act_type.is_not(None)).distinct().order_by(Publication.act_type)
    )

    return templates.TemplateResponse(
        request,
        "partials/results.html",
        {
            "publications": rows, "total": total, "q": q, "next_cursor": next_cursor,
            "date_from": date_from, "date_to": date_to,
            "organ": organ, "section": section, "act_type": act_type,
            "organs": [r[0] for r in organs_result.all()],
            "sections": [r[0] for r in sections_result.all()],
            "act_types": [r[0] for r in act_types_result.all()],
        },
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
