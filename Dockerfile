FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
COPY src/ src/
COPY migrations/ migrations/
COPY alembic.ini .
COPY entrypoint.sh .

RUN pip install --no-cache-dir . && \
    apt-get purge -y --auto-remove build-essential && \
    chmod +x entrypoint.sh

EXPOSE 8000

CMD ["./entrypoint.sh"]
