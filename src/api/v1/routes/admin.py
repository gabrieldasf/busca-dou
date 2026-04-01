"""Admin endpoints - backfill operations."""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.v1.deps import get_api_key
from src.app.database import get_session
from src.models.api_key import ApiKey
from src.models.publication import Publication
from src.services.ai import generate_embedding

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


class BackfillResponse(BaseModel):
    total: int
    updated: int
    failed: int


@router.post("/backfill-embeddings", response_model=BackfillResponse)
async def backfill_embeddings(
    session: Annotated[AsyncSession, Depends(get_session)],
    api_key: Annotated[ApiKey, Depends(get_api_key)],
) -> BackfillResponse:
    """Generate embeddings for all publications missing them."""
    stmt = select(Publication).where(Publication.embedding.is_(None))
    result = await session.execute(stmt)
    pubs = list(result.scalars().all())

    updated = 0
    failed = 0

    for pub in pubs:
        try:
            embedding = await generate_embedding(pub.body)
            pub.embedding = embedding
            updated += 1
            logger.info("Embedded publication %s", pub.id)
        except Exception:
            failed += 1
            logger.warning("Failed to embed publication %s", pub.id, exc_info=True)
        await asyncio.sleep(0.5)

    await session.commit()

    return BackfillResponse(total=len(pubs), updated=updated, failed=failed)
