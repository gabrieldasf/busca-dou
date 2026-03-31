"""PDF parser for Brazilian Official Gazettes using pdfplumber.

Extracts text from vector-text PDFs and splits into structured blocks
by detecting section headers, organ names, and act types.
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path

import pdfplumber

from src.parsers.base import BaseParser, ParsedBlock

logger = logging.getLogger(__name__)

# Section header patterns - uppercase titles that start a new section
_SECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^(SECRETARIA\s+DE\s+ESTADO\s+DE\s+.+)$", re.MULTILINE),
    re.compile(r"^(ATO\s+DO\s+GOVERNADOR.*)$", re.MULTILINE),
    re.compile(r"^(ATO\s+DO\s+PODER\s+EXECUTIVO.*)$", re.MULTILINE),
    re.compile(r"^(GOVERNO\s+DO\s+ESTADO\s+DO\s+RIO\s+DE\s+JANEIRO.*)$", re.MULTILINE),
    re.compile(r"^(PROCURADORIA[\s-]GERAL\s+DO\s+ESTADO.*)$", re.MULTILINE),
    re.compile(r"^(DEFENSORIA\s+P[UÚ]BLICA.*)$", re.MULTILINE),
    re.compile(r"^(TRIBUNAL\s+DE\s+CONTAS.*)$", re.MULTILINE),
    re.compile(r"^(MINIST[EÉ]RIO\s+P[UÚ]BLICO.*)$", re.MULTILINE),
    re.compile(r"^(ASSEMBLEIA\s+LEGISLATIVA.*)$", re.MULTILINE),
    re.compile(r"^(PODER\s+JUDICI[AÁ]RIO.*)$", re.MULTILINE),
    re.compile(r"^(PREFEITURA\s+.+)$", re.MULTILINE),
    re.compile(r"^(C[AÂ]MARA\s+MUNICIPAL\s+.+)$", re.MULTILINE),
]

# Organ patterns - entities that publish acts
_ORGAN_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"SECRETARIA\s+DE\s+ESTADO\s+DE\s+[\w\s,]+", re.IGNORECASE),
    re.compile(r"SECRETARIA\s+(?:MUNICIPAL|ESTADUAL)\s+DE\s+[\w\s,]+", re.IGNORECASE),
    re.compile(r"PROCURADORIA[\s-]GERAL\s+DO\s+ESTADO", re.IGNORECASE),
    re.compile(r"DEFENSORIA\s+P[UÚ]BLICA(?:\s+(?:GERAL|DO\s+ESTADO))?", re.IGNORECASE),
    re.compile(r"TRIBUNAL\s+DE\s+CONTAS\s+DO\s+ESTADO", re.IGNORECASE),
    re.compile(r"MINIST[EÉ]RIO\s+P[UÚ]BLICO(?:\s+DO\s+ESTADO)?", re.IGNORECASE),
    re.compile(r"CORPO\s+DE\s+BOMBEIROS\s+MILITAR", re.IGNORECASE),
    re.compile(r"POL[IÍ]CIA\s+(?:CIVIL|MILITAR)", re.IGNORECASE),
    re.compile(r"DETRAN[\s-]?RJ", re.IGNORECASE),
    re.compile(r"JUNTA\s+COMERCIAL", re.IGNORECASE),
    re.compile(r"PREFEITURA\s+(?:MUNICIPAL\s+)?DE\s+[\w\s]+", re.IGNORECASE),
    re.compile(r"C[AÂ]MARA\s+MUNICIPAL\s+DE\s+[\w\s]+", re.IGNORECASE),
]

# Act type patterns
_ACT_TYPES: dict[str, re.Pattern[str]] = {
    "DECRETO": re.compile(r"^DECRETO\s+(?:N[.ºO°]\s*)?\d+", re.MULTILINE | re.IGNORECASE),
    "LEI": re.compile(r"^LEI\s+(?:N[.ºO°]\s*)?\d+", re.MULTILINE | re.IGNORECASE),
    "LEI COMPLEMENTAR": re.compile(
        r"^LEI\s+COMPLEMENTAR\s+(?:N[.ºO°]\s*)?\d+", re.MULTILINE | re.IGNORECASE
    ),
    "RESOLUCAO": re.compile(r"^RESOLU[CÇ][AÃ]O\s+(?:N[.ºO°]\s*)?\d+", re.MULTILINE | re.IGNORECASE),
    "PORTARIA": re.compile(r"^PORTARIA\s+(?:N[.ºO°]\s*)?\d+", re.MULTILINE | re.IGNORECASE),
    "EDITAL": re.compile(r"^EDITAL\s+(?:N[.ºO°]\s*)?\d+", re.MULTILINE | re.IGNORECASE),
    "EXTRATO": re.compile(r"^EXTRATO\s+(?:DE\s+)?", re.MULTILINE | re.IGNORECASE),
    "ATO": re.compile(
        r"^ATO\s+(?:DO\s+(?:GOVERNADOR|SECRET[AÁ]RIO|PRESIDENTE))",
        re.MULTILINE | re.IGNORECASE,
    ),
    "DESPACHO": re.compile(r"^DESPACHO\s+(?:N[.ºO°]\s*)?\d*", re.MULTILINE | re.IGNORECASE),
    "INSTRUCAO NORMATIVA": re.compile(
        r"^INSTRU[CÇ][AÃ]O\s+NORMATIVA", re.MULTILINE | re.IGNORECASE
    ),
    "DELIBERACAO": re.compile(r"^DELIBERA[CÇ][AÃ]O", re.MULTILINE | re.IGNORECASE),
    "AVISO": re.compile(r"^AVISO\s+(?:N[.ºO°]\s*)?\d*", re.MULTILINE | re.IGNORECASE),
    "CONVOCACAO": re.compile(r"^CONVOCA[CÇ][AÃ]O", re.MULTILINE | re.IGNORECASE),
    "ERRATA": re.compile(r"^ERRATA", re.MULTILINE | re.IGNORECASE),
    "RETIFICACAO": re.compile(r"^RETIFICA[CÇ][AÃ]O", re.MULTILINE | re.IGNORECASE),
}

# Minimum text length for a valid block (skip noise/headers)
_MIN_BLOCK_LENGTH = 50


class PDFParser(BaseParser):
    """Parser for IOERJ PDF gazettes using pdfplumber."""

    async def parse(self, file_path: Path) -> list[ParsedBlock]:
        """Parse a PDF file into structured blocks.

        Runs pdfplumber in a thread since it's CPU-bound.
        """
        return await asyncio.to_thread(self._parse_sync, file_path)

    def _parse_sync(self, file_path: Path) -> list[ParsedBlock]:
        """Synchronous PDF parsing implementation."""
        blocks: list[ParsedBlock] = []

        try:
            with pdfplumber.open(file_path) as pdf:
                for page_num, page in enumerate(pdf.pages, start=1):
                    text = page.extract_text()
                    if not text:
                        continue

                    page_blocks = self._split_into_blocks(text, page_num)
                    blocks.extend(page_blocks)
        except Exception:
            logger.exception("Failed to parse PDF: %s", file_path)

        logger.debug("Extracted %d blocks from %s", len(blocks), file_path.name)
        return blocks

    def _split_into_blocks(self, text: str, page_number: int) -> list[ParsedBlock]:
        """Split page text into logical blocks based on section headers."""
        # Find all section header positions
        splits: list[tuple[int, str]] = []
        for pattern in _SECTION_PATTERNS:
            for match in pattern.finditer(text):
                splits.append((match.start(), match.group(1).strip()))

        if not splits:
            # No section headers found - treat entire page as one block
            if len(text.strip()) >= _MIN_BLOCK_LENGTH:
                return [
                    ParsedBlock(
                        text=text.strip(),
                        section=None,
                        organ=_detect_organ(text),
                        act_type=_detect_act_type(text),
                        page_number=page_number,
                    )
                ]
            return []

        # Sort splits by position
        splits.sort(key=lambda x: x[0])

        blocks: list[ParsedBlock] = []

        # Text before first header
        if splits[0][0] > 0:
            pre_text = text[: splits[0][0]].strip()
            if len(pre_text) >= _MIN_BLOCK_LENGTH:
                blocks.append(
                    ParsedBlock(
                        text=pre_text,
                        section=None,
                        organ=_detect_organ(pre_text),
                        act_type=_detect_act_type(pre_text),
                        page_number=page_number,
                    )
                )

        # Blocks between headers
        for i, (pos, section_name) in enumerate(splits):
            end = splits[i + 1][0] if i + 1 < len(splits) else len(text)
            block_text = text[pos:end].strip()

            if len(block_text) < _MIN_BLOCK_LENGTH:
                continue

            blocks.append(
                ParsedBlock(
                    text=block_text,
                    section=section_name,
                    organ=_detect_organ(block_text),
                    act_type=_detect_act_type(block_text),
                    page_number=page_number,
                )
            )

        return blocks


def _detect_organ(text: str) -> str | None:
    """Detect the publishing organ from text content."""
    for pattern in _ORGAN_PATTERNS:
        match = pattern.search(text[:500])  # Only check start of text
        if match:
            return match.group(0).strip()
    return None


def _detect_act_type(text: str) -> str | None:
    """Detect the type of official act from text content."""
    for act_name, pattern in _ACT_TYPES.items():
        if pattern.search(text[:300]):  # Only check start of text
            return act_name
    return None
