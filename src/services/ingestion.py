"""Ingestion service - orchestrates scrape, parse, store, and index pipeline."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.config import settings
from src.scrapers.base import ScrapedPublication
from src.scrapers.ioerj import IOERJAdapter
from src.services.ai import generate_embedding
from src.services.db import get_or_create_source, insert_publications
from src.services.storage import StorageService

logger = logging.getLogger(__name__)

# Adapter registry
_ADAPTERS: dict[str, type] = {
    "ioerj": IOERJAdapter,
}

# Source metadata
_SOURCE_META: dict[str, dict[str, str]] = {
    "ioerj": {
        "name": "IOERJ - Imprensa Oficial do Estado do Rio de Janeiro",
        "base_url": "https://portal.ioerj.com.br",
        "adapter_class": "src.scrapers.ioerj.IOERJAdapter",
    },
}


class IngestionService:
    """Orchestrates the full ingestion pipeline for a gazette edition."""

    def __init__(
        self,
        session: AsyncSession,
        storage: StorageService | None = None,
    ) -> None:
        self._session = session
        self._storage = storage or StorageService()

    async def ingest_edition(self, source_slug: str, edition_date: date) -> int:
        """Scrape, parse, store, and index a full gazette edition.

        Flow:
        1. Resolve adapter for the source
        2. Scrape the edition (downloads PDFs, parses text)
        3. Store raw PDFs via StorageService
        4. Insert publications into PostgreSQL
        5. Return count of ingested publications

        Args:
            source_slug: Identifier for the gazette source (e.g. "ioerj")
            edition_date: Date of the edition to ingest

        Returns:
            Number of publications ingested

        Raises:
            ValueError: If source_slug is not registered
        """
        if source_slug not in _ADAPTERS:
            msg = f"Unknown source: {source_slug}. Available: {list(_ADAPTERS.keys())}"
            raise ValueError(msg)

        meta = _SOURCE_META[source_slug]
        source = await get_or_create_source(
            self._session,
            name=meta["name"],
            slug=source_slug,
            base_url=meta["base_url"],
            adapter_class=meta["adapter_class"],
        )

        adapter = _ADAPTERS[source_slug]()
        try:
            scraped = await adapter.scrape_edition(edition_date)
            pdf_cache = adapter.pdf_cache if hasattr(adapter, "pdf_cache") else {}
        finally:
            if hasattr(adapter, "close"):
                await adapter.close()

        if not scraped:
            logger.warning("No publications scraped for %s on %s", source_slug, edition_date)
            return 0

        logger.info(
            "Scraped %d raw publications from %s for %s",
            len(scraped),
            source_slug,
            edition_date,
        )

        # Store PDFs
        for part_code, pdf_bytes in pdf_cache.items():
            await self._storage.save_pdf(source_slug, edition_date, part_code, pdf_bytes)

        pub_dicts = await self._process_publications(
            source.id,
            source_slug,
            edition_date,
            scraped,
            pdf_cache,
        )

        count = await insert_publications(self._session, pub_dicts)

        if settings.openrouter_api_key:
            await self._generate_embeddings(pub_dicts)

        await self._session.commit()

        logger.info(
            "Ingestion complete: %d publications from %s for %s",
            count,
            source_slug,
            edition_date,
        )
        return count

    async def _generate_embeddings(self, pub_dicts: list[dict[str, Any]]) -> None:
        """Generate embeddings for ingested publications (best-effort)."""
        from src.models.publication import Publication

        for pub_data in pub_dicts:
            try:
                body = pub_data.get("body", "")
                if not body:
                    continue
                embedding = await generate_embedding(body)
                stmt = (
                    select(Publication)
                    .where(Publication.body == body)
                    .where(Publication.published_at == pub_data["published_at"])
                    .limit(1)
                )
                result = await self._session.execute(stmt)
                pub = result.scalar_one_or_none()
                if pub:
                    pub.embedding = embedding
            except Exception:
                logger.warning("Failed to generate embedding, skipping", exc_info=True)

    async def _process_publications(
        self,
        source_id: Any,
        source_slug: str,
        edition_date: date,
        scraped: list[ScrapedPublication],
        pdf_cache: dict[str, bytes],
    ) -> list[dict[str, Any]]:
        """Convert scraped publications to DB-ready dicts with PDF storage keys."""
        pub_dicts: list[dict[str, Any]] = []

        for pub in scraped:
            part_code = "unknown"
            if pub.metadata and "part_code" in pub.metadata:
                part_code = pub.metadata["part_code"]

            raw_pdf_key: str | None = None
            if part_code in pdf_cache:
                raw_pdf_key = StorageService._build_key(source_slug, edition_date, part_code)

            pub_dict: dict[str, Any] = {
                "source_id": source_id,
                "title": pub.title,
                "body": pub.body,
                "section": pub.section,
                "organ": pub.organ,
                "act_type": pub.act_type,
                "published_at": pub.published_at,
                "page_number": pub.page_number,
                "pdf_url": pub.pdf_url,
                "raw_pdf_key": raw_pdf_key,
                "metadata_extra": pub.metadata,
            }
            pub_dicts.append(pub_dict)

        return pub_dicts
