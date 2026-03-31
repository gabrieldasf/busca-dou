"""Publication search and detail endpoints."""

from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.v1.deps import get_api_key
from src.api.v1.schemas import (
    PaginationMeta,
    PublicationDetail,
    PublicationListResponse,
    PublicationSummary,
    decode_cursor,
    encode_cursor,
)
from src.app.config import settings
from src.app.database import get_session
from src.models.api_key import ApiKey
from src.services.ai import generate_embedding
from src.services.db import get_publication_by_id, search_publications

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/publications", tags=["publications"])


@router.get("", response_model=PublicationListResponse)
async def search(
    session: Annotated[AsyncSession, Depends(get_session)],
    api_key: Annotated[ApiKey, Depends(get_api_key)],
    q: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    organ: str | None = None,
    section: str | None = None,
    act_type: str | None = None,
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
) -> PublicationListResponse:
    """Search publications with full-text + semantic search."""
    cursor_date = None
    cursor_id = None
    if cursor:
        cursor_date, cursor_id = decode_cursor(cursor)

    query_embedding = None
    if q and settings.openrouter_api_key:
        try:
            query_embedding = await generate_embedding(q)
        except Exception:
            logger.warning("Embedding generation failed, falling back to keyword search")

    rows, has_more = await search_publications(
        session,
        q=q,
        query_embedding=query_embedding,
        date_from=date_from,
        date_to=date_to,
        organ=organ,
        section=section,
        act_type=act_type,
        cursor_date=cursor_date,
        cursor_id=cursor_id,
        limit=limit,
    )

    data = [
        PublicationSummary(
            id=row.id,
            title=row.title,
            snippet=row.snippet,
            section=row.section,
            organ=row.organ,
            act_type=row.act_type,
            published_at=row.published_at,
            page_number=row.page_number,
            pdf_url=row.pdf_url,
            relevance=float(row.relevance) if row.relevance is not None else None,
        )
        for row in rows
    ]

    next_cursor = None
    if has_more and data:
        last = data[-1]
        next_cursor = encode_cursor(last.published_at, last.id)

    return PublicationListResponse(
        data=data,
        meta=PaginationMeta(has_more=has_more, next_cursor=next_cursor),
    )


@router.get("/{publication_id}", response_model=PublicationDetail)
async def get_detail(
    publication_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    api_key: Annotated[ApiKey, Depends(get_api_key)],
) -> PublicationDetail:
    """Get a single publication with full body."""
    pub = await get_publication_by_id(session, publication_id)
    if pub is None:
        raise HTTPException(status_code=404, detail="Publication not found")
    return PublicationDetail.model_validate(pub)
