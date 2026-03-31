import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import (
    Column,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class Publication(Base):
    __tablename__ = "publications"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sources.id"), nullable=False
    )
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    body_tsv = Column(
        TSVECTOR,
        Computed("to_tsvector('portuguese', body)", persisted=True),
    )
    section: Mapped[str | None] = mapped_column(String(255), nullable=True)
    organ: Mapped[str | None] = mapped_column(String(255), nullable=True)
    act_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    published_at: Mapped[date] = mapped_column(Date, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pdf_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_pdf_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_extra: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    __table_args__ = (
        Index("idx_publications_tsv", body_tsv, postgresql_using="gin"),
        Index("idx_publications_source_date", "source_id", published_at.desc()),
        Index("idx_publications_organ", "organ"),
    )
