"""Local filesystem storage for downloaded PDFs.

Stores PDFs at: data/pdfs/{source}/{YYYY}/{MM}/{DD}/{part}.pdf
Interface is designed for future S3 migration.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from src.app.config import settings

logger = logging.getLogger(__name__)


def _get_base_dir() -> Path:
    """Get base directory for PDF storage from settings or default."""
    storage_dir = getattr(settings, "storage_dir", None)
    if storage_dir:
        return Path(str(storage_dir))
    return Path("data/pdfs")


class StorageService:
    """Local filesystem storage with S3-ready interface."""

    def __init__(self, base_dir: Path | None = None) -> None:
        self._base_dir = base_dir or _get_base_dir()

    async def save_pdf(
        self,
        source: str,
        edition_date: date,
        part: str,
        content: bytes,
    ) -> str:
        """Save PDF content and return the storage key.

        Storage key format: {source}/{YYYY}/{MM}/{DD}/{part}.pdf
        """
        key = self._build_key(source, edition_date, part)
        path = self._base_dir / key

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

        logger.info("Stored PDF: %s (%d bytes)", key, len(content))
        return key

    async def get_pdf_path(self, key: str) -> Path:
        """Get the local filesystem path for a stored PDF.

        Raises FileNotFoundError if the PDF doesn't exist.
        """
        path = self._base_dir / key
        if not path.exists():
            msg = f"PDF not found: {key}"
            raise FileNotFoundError(msg)
        return path

    async def exists(self, key: str) -> bool:
        """Check if a PDF exists in storage."""
        return (self._base_dir / key).exists()

    @staticmethod
    def _build_key(source: str, edition_date: date, part: str) -> str:
        """Build storage key from components.

        Returns path like: ioerj/2024/03/15/I.pdf
        """
        return (
            f"{source}/{edition_date.year:04d}/{edition_date.month:02d}"
            f"/{edition_date.day:02d}/{part}.pdf"
        )
