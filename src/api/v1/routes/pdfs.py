"""PDF serving routes - provide stored PDFs for visualization."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from src.services.storage import StorageService

router = APIRouter(prefix="/pdfs", tags=["pdfs"])

_storage = StorageService()


@router.get("/{source}/{year}/{month}/{day}/{part}.pdf")
async def get_pdf(
    source: str,
    year: int,
    month: int,
    day: int,
    part: str,
) -> FileResponse:
    """Serve a stored gazette PDF for viewing/download."""
    key = f"{source}/{year:04d}/{month:02d}/{day:02d}/{part}.pdf"

    try:
        path = await _storage.get_pdf_path(key)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"PDF not found: {key}")  # noqa: B904

    return FileResponse(
        path=path,
        media_type="application/pdf",
        filename=f"{source}-{year}{month:02d}{day:02d}-{part}.pdf",
    )
