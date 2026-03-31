"""Database operations for publications and sources."""

from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import Any

from sqlalchemy import Row, func, literal_column, select, tuple_
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


async def search_publications(
    session: AsyncSession,
    *,
    q: str | None = None,
    query_embedding: list[float] | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    organ: str | None = None,
    section: str | None = None,
    act_type: str | None = None,
    cursor_date: date | None = None,
    cursor_id: uuid.UUID | None = None,
    limit: int = 20,
) -> tuple[list[Row], bool]:
    """Search publications with hybrid keyword + semantic ranking.

    Returns (rows, has_more). Each row has: id, title, snippet, section,
    organ, act_type, published_at, page_number, pdf_url, relevance.
    """
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

    if date_from is not None:
        stmt = stmt.where(Publication.published_at >= date_from)
    if date_to is not None:
        stmt = stmt.where(Publication.published_at <= date_to)
    if organ is not None:
        stmt = stmt.where(Publication.organ == organ)
    if section is not None:
        stmt = stmt.where(Publication.section == section)
    if act_type is not None:
        stmt = stmt.where(Publication.act_type == act_type)

    if cursor_date is not None and cursor_id is not None:
        stmt = stmt.where(
            tuple_(Publication.published_at, Publication.id) < tuple_(cursor_date, cursor_id)
        )

    stmt = stmt.order_by(Publication.published_at.desc(), Publication.id.desc())
    stmt = stmt.limit(limit + 1)

    result = await session.execute(stmt)
    rows = list(result.all())

    has_more = len(rows) > limit
    if has_more:
        rows = rows[:limit]

    return rows, has_more


async def get_publication_by_id(
    session: AsyncSession,
    publication_id: uuid.UUID,
) -> Publication | None:
    """Get a single publication by ID."""
    stmt = select(Publication).where(Publication.id == publication_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def list_sources_with_stats(session: AsyncSession) -> list[Row]:
    """List all sources with publication count and latest date."""
    stmt = (
        select(
            Source.id,
            Source.name,
            Source.slug,
            Source.is_active,
            func.count(Publication.id).label("publication_count"),
            func.max(Publication.published_at).label("latest_publication"),
        )
        .outerjoin(Publication, Publication.source_id == Source.id)
        .group_by(Source.id)
        .order_by(Source.name)
    )
    result = await session.execute(stmt)
    return list(result.all())
