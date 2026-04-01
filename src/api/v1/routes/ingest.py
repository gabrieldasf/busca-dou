"""Ingestion API routes - trigger scraping of gazette editions."""

from __future__ import annotations

import logging
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import CursorResult, delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.v1.deps import get_api_key
from src.app.database import get_session
from src.models.api_key import ApiKey
from src.models.publication import Publication
from src.services.ingestion import IngestionService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ingest", tags=["ingestion"])


class IngestRequest(BaseModel):
    source: str = "ioerj"
    date: date


class IngestResponse(BaseModel):
    source: str
    date: date
    publications_count: int
    status: str


@router.post("", response_model=IngestResponse)
async def ingest_edition(
    request: IngestRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    api_key: Annotated[ApiKey, Depends(get_api_key)],
) -> IngestResponse:
    """Trigger ingestion of a gazette edition.

    Downloads PDFs, parses text, and indexes publications.
    """
    service = IngestionService(session)
    try:
        count = await service.ingest_edition(request.source, request.date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return IngestResponse(
        source=request.source,
        date=request.date,
        publications_count=count,
        status="completed",
    )


@router.post("/reingest", response_model=IngestResponse)
async def reingest_edition(
    request: IngestRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    api_key: Annotated[ApiKey, Depends(get_api_key)],
) -> IngestResponse:
    """Delete existing publications for a date and re-ingest."""
    del_stmt = delete(Publication).where(Publication.published_at == request.date)
    raw_result = await session.execute(del_stmt)
    cursor_result: CursorResult[Any] = raw_result  # type: ignore[assignment]
    deleted = cursor_result.rowcount
    logger.info("Deleted %d existing publications for %s", deleted, request.date)

    service = IngestionService(session)
    try:
        count = await service.ingest_edition(request.source, request.date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return IngestResponse(
        source=request.source,
        date=request.date,
        publications_count=count,
        status="reingested",
    )
