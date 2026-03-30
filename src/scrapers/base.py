from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date


@dataclass
class ScrapedPublication:
    title: str | None
    body: str
    section: str | None
    organ: str | None
    act_type: str | None
    published_at: date
    page_number: int | None
    pdf_url: str | None
    metadata: dict | None = None


class BaseAdapter(ABC):
    """Interface base para adapters de fontes de Diários Oficiais."""

    @abstractmethod
    async def list_available_dates(self, year: int, month: int) -> list[date]:
        """Retorna datas com publicações disponíveis no mês."""
        ...

    @abstractmethod
    async def scrape_edition(self, edition_date: date) -> list[ScrapedPublication]:
        """Extrai todas as publicações de uma edição."""
        ...
