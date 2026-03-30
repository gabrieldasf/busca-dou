# BuscaDOU

API de scraping e consulta de Diarios Oficiais do Brasil.

## Quick Start

```bash
# Dev local com Docker
docker compose up -d

# Sem Docker
pip install -e ".[dev]"
uvicorn src.app.main:app --reload
```

## Endpoints

- `GET /health` - Health check
- `GET /docs` - OpenAPI docs (Swagger)
- `GET /redoc` - ReDoc

## Stack

Python 3.12 | FastAPI | PostgreSQL (tsvector) | agent-browser | pdfplumber
