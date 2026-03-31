from datetime import UTC, datetime

from fastapi import FastAPI
from sqlalchemy import text

from src.api.v1.routes.ingest import router as ingest_router
from src.api.v1.routes.pdfs import router as pdfs_router
from src.api.v1.routes.publications import router as publications_router
from src.api.v1.routes.sources import router as sources_router
from src.app.config import settings
from src.app.database import engine

app = FastAPI(
    title="BuscaDOU",
    description="API de scraping e consulta de Diários Oficiais do Brasil",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.include_router(ingest_router, prefix="/api/v1")
app.include_router(pdfs_router, prefix="/api/v1")
app.include_router(publications_router, prefix="/api/v1")
app.include_router(sources_router, prefix="/api/v1")


@app.get("/health")
async def health_check() -> dict[str, str]:
    db_status = "disconnected"
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            db_status = "connected"
    except Exception:
        db_status = "error"

    return {
        "status": "ok",
        "version": "0.1.0",
        "environment": settings.environment,
        "db": db_status,
        "timestamp": datetime.now(UTC).isoformat(),
    }
