"""Database operations for publications and sources."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.publication import Publication
from src.models.source import Source

logger = logging.getLogger(__name__)


async def get_or_create_source(
    session: AsyncSession,
    name: str,
    slug: str,
    base_url: str,
    adapter_class: str,
) -> Source:
    """Get an existing source by slug, or create a new one.

    Returns the Source instance (existing or newly created).
    """
    stmt = select(Source).where(Source.slug == slug)
    result = await session.execute(stmt)
    source = result.scalar_one_or_none()

    if source is not None:
        return source

    source = Source(
        id=uuid.uuid4(),
        name=name,
        slug=slug,
        base_url=base_url,
        adapter_class=adapter_class,
    )
    session.add(source)
    await session.flush()
    logger.info("Created source: %s (%s)", name, slug)
    return source


async def insert_publications(
    session: AsyncSession,
    publications: list[dict[str, Any]],
) -> int:
    """Batch insert publications into the database.

    Each dict in the list must contain keys matching Publication model columns.
    Returns count of inserted records.
    """
    if not publications:
        return 0

    objects = []
    for pub_data in publications:
        pub = Publication(
            id=uuid.uuid4(),
            source_id=pub_data["source_id"],
            title=pub_data.get("title"),
            body=pub_data["body"],
            section=pub_data.get("section"),
            organ=pub_data.get("organ"),
            act_type=pub_data.get("act_type"),
            published_at=pub_data["published_at"],
            page_number=pub_data.get("page_number"),
            pdf_url=pub_data.get("pdf_url"),
            raw_pdf_key=pub_data.get("raw_pdf_key"),
            metadata_extra=pub_data.get("metadata_extra"),
        )
        objects.append(pub)

    session.add_all(objects)
    await session.flush()

    count = len(objects)
    logger.info("Inserted %d publications", count)
    return count
