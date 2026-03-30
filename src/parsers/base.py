from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ParsedBlock:
    text: str
    section: str | None = None
    organ: str | None = None
    act_type: str | None = None
    page_number: int | None = None


class BaseParser(ABC):
    """Interface base para parsers de conteúdo de Diários Oficiais."""

    @abstractmethod
    async def parse(self, file_path: Path) -> list[ParsedBlock]:
        """Parseia um arquivo (PDF/HTML) em blocos estruturados."""
        ...
