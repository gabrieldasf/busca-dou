"""OpenRouter AI client for embeddings and summaries."""

from __future__ import annotations

import logging

from openai import AsyncOpenAI

from src.app.config import settings

logger = logging.getLogger(__name__)

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client  # noqa: PLW0603
    if _client is None:
        _client = AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=settings.openrouter_api_key,
        )
    return _client


async def generate_embedding(text: str) -> list[float]:
    """Generate embedding vector for text via OpenRouter.

    Truncates to ~30k chars (~8k tokens) to stay within model limits.
    Returns list of floats with length = settings.embedding_dimensions.
    """
    truncated = text[:30000]
    client = _get_client()
    response = await client.embeddings.create(
        model=settings.embedding_model,
        input=truncated,
    )
    return response.data[0].embedding


async def summarize_publication(body: str) -> str:
    """Generate a short summary of a publication via OpenRouter.

    Returns a 2-3 sentence summary in Portuguese.
    """
    truncated = body[:15000]
    client = _get_client()
    response = await client.chat.completions.create(
        model=settings.summary_model,
        messages=[
            {
                "role": "system",
                "content": (
                    "Resuma a publicacao oficial abaixo em 2-3 frases objetivas em portugues. "
                    "Foque no que mudou, quem e afetado e prazos. Sem introducao."
                ),
            },
            {"role": "user", "content": truncated},
        ],
        max_tokens=300,
        temperature=0.3,
    )
    return response.choices[0].message.content or ""
