"""Source listing endpoint."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.v1.deps import get_api_key
from src.api.v1.schemas import SourceListResponse, SourceResponse
from src.app.database import get_session
from src.models.api_key import ApiKey
from src.services.db import list_sources_with_stats

router = APIRouter(prefix="/sources", tags=["sources"])


@router.get("", response_model=SourceListResponse)
async def list_sources(
    session: Annotated[AsyncSession, Depends(get_session)],
    api_key: Annotated[ApiKey, Depends(get_api_key)],
) -> SourceListResponse:
    """List all gazette sources with publication stats."""
    rows = await list_sources_with_stats(session)
    data = [
        SourceResponse(
            id=row.id,
            name=row.name,
            slug=row.slug,
            is_active=row.is_active,
            publication_count=row.publication_count,
            latest_publication=row.latest_publication,
        )
        for row in rows
    ]
    return SourceListResponse(data=data)
