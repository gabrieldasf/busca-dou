"""Pydantic schemas for API responses and cursor-based pagination."""

from __future__ import annotations

import base64
import json
import uuid
from datetime import date, datetime

from pydantic import BaseModel

# --- Cursor helpers ---


def encode_cursor(published_at: date, pub_id: uuid.UUID) -> str:
    """Encode pagination cursor as opaque base64 string."""
    payload = json.dumps({"d": published_at.isoformat(), "id": str(pub_id)})
    return base64.urlsafe_b64encode(payload.encode()).decode()


def decode_cursor(cursor: str) -> tuple[date, uuid.UUID]:
    """Decode opaque cursor back to (published_at, id) tuple."""
    payload = json.loads(base64.urlsafe_b64decode(cursor.encode()))
    return date.fromisoformat(payload["d"]), uuid.UUID(payload["id"])


# --- Publication schemas ---


class PublicationSummary(BaseModel):
    """Publication in search results (no full body)."""

    id: uuid.UUID
    title: str | None = None
    snippet: str | None = None
    section: str | None = None
    organ: str | None = None
    act_type: str | None = None
    published_at: date
    page_number: int | None = None
    pdf_url: str | None = None
    relevance: float | None = None

    model_config = {"from_attributes": True}


class PublicationDetail(BaseModel):
    """Single publication with full body."""

    id: uuid.UUID
    title: str | None = None
    body: str
    section: str | None = None
    organ: str | None = None
    act_type: str | None = None
    published_at: date
    page_number: int | None = None
    pdf_url: str | None = None
    metadata_extra: dict | None = None
    source_id: uuid.UUID
    created_at: datetime

    model_config = {"from_attributes": True}


class PaginationMeta(BaseModel):
    """Cursor-based pagination metadata."""

    has_more: bool
    next_cursor: str | None = None


class PublicationListResponse(BaseModel):
    """Paginated list of publications."""

    data: list[PublicationSummary]
    meta: PaginationMeta


# --- Source schemas ---


class SourceResponse(BaseModel):
    """Source with publication stats."""

    id: uuid.UUID
    name: str
    slug: str
    is_active: bool
    publication_count: int = 0
    latest_publication: date | None = None

    model_config = {"from_attributes": True}


class SourceListResponse(BaseModel):
    """List of available sources."""

    data: list[SourceResponse]
