"""Ingestion API routes - trigger scraping of gazette editions."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.database import get_session
from src.services.ingestion import IngestionService

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
