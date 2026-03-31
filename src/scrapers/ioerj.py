"""IOERJ (Imprensa Oficial do Estado do Rio de Janeiro) adapter.

Scrapes editions from portal.ioerj.com.br by:
1. Selecting an edition date via base64-encoded date parameter
2. Extracting caderno UUIDs from triple-base64 session tokens
3. Downloading PDFs using UUID with 'P' inserted at position 12
4. Parsing PDF text with pdfplumber
"""

from __future__ import annotations

import asyncio
import base64
import logging
import re
from datetime import date
from pathlib import Path
from typing import Any

import httpx

from src.parsers.pdf_parser import PDFParser
from src.scrapers.base import BaseAdapter, ScrapedPublication

logger = logging.getLogger(__name__)

BASE_URL = "https://portal.ioerj.com.br/portal/modules/conteudoonline"

# Cadernos IOERJ: id -> (part_code, name)
CADERNOS: dict[int, tuple[str, str]] = {
    12: ("I", "Poder Executivo"),
    1: ("IA", "Ministerio Publico"),
    2: ("IB", "Tribunal de Contas"),
    13: ("I-DPGE", "Defensoria Publica"),
    20: ("I-JC", "Junta Comercial"),
    3: ("II", "Poder Legislativo"),
    6: ("III-E", "Poder Judiciario Estadual"),
    7: ("III-F-Federal", "Justica Federal"),
    10: ("III-F-Trabalho", "Justica do Trabalho"),
    11: ("III-F-Eleitoral", "Justica Eleitoral"),
    5: ("IV", "Municipalidades"),
    4: ("V", "Publicacoes a Pedido"),
    18: ("DO-Campos", "Poder Executivo (Campos)"),
}

# Max retries for HTTP requests
_MAX_RETRIES = 3
_RETRY_BACKOFF_BASE = 1.0


class IOERJAdapter(BaseAdapter):
    """Adapter for scraping IOERJ (Rio de Janeiro state gazette)."""

    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        self._client = http_client
        self._owns_client = http_client is None
        self._parser = PDFParser()
        self.pdf_cache: dict[str, bytes] = {}

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0, connect=10.0),
                follow_redirects=True,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                },
            )
        return self._client

    async def close(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    # --- Public interface ---

    async def list_available_dates(self, year: int, month: int) -> list[date]:
        """Return dates with published editions for the given month.

        Requests the edition selection page and parses the HTML calendar
        to find dates that have publication links (green/active dates).
        """
        target = date(year, month, 1)
        encoded = self._encode_date(target)
        url = f"{BASE_URL}/do_seleciona_edicao.php?data={encoded}"

        html = await self._fetch_text(url)
        return self._parse_calendar_dates(html, year, month)

    async def scrape_edition(self, edition_date: date) -> list[ScrapedPublication]:
        """Scrape all cadernos for a given edition date.

        Flow:
        1. Request edition selection page for the date
        2. Extract caderno session tokens from HTML
        3. Decode triple-base64 to get UUIDs
        4. Download each caderno PDF
        5. Parse PDF text into publications
        """
        encoded = self._encode_date(edition_date)
        url = f"{BASE_URL}/do_seleciona_edicao.php?data={encoded}"

        html = await self._fetch_text(url)
        cadernos = self._parse_cadernos(html)

        if not cadernos:
            logger.warning("No cadernos found for date %s", edition_date)
            return []

        publications: list[ScrapedPublication] = []

        for caderno_id, session_token in cadernos:
            try:
                pubs = await self._scrape_caderno(edition_date, caderno_id, session_token)
                publications.extend(pubs)
            except Exception:
                part_code = CADERNOS.get(caderno_id, (str(caderno_id), "Desconhecido"))[0]
                logger.exception(
                    "Failed to scrape caderno %s (%s) for %s",
                    caderno_id,
                    part_code,
                    edition_date,
                )

        logger.info(
            "Scraped %d publications from %d cadernos for %s",
            len(publications),
            len(cadernos),
            edition_date,
        )
        return publications

    # --- Caderno scraping ---

    async def _scrape_caderno(
        self,
        edition_date: date,
        caderno_id: int,
        session_token: str,
    ) -> list[ScrapedPublication]:
        """Download and parse a single caderno PDF."""
        part_code, part_name = CADERNOS.get(caderno_id, (str(caderno_id), "Desconhecido"))

        uuid_raw = self._decode_triple_base64(session_token)
        # UUID is the first 36 chars (standard UUID length), rest is timestamp
        uuid_str = uuid_raw[:36] if len(uuid_raw) >= 36 else uuid_raw

        pdf_url = self._build_pdf_url(uuid_str)
        logger.info("Downloading caderno %s (%s): %s", part_code, part_name, pdf_url)

        pdf_bytes = await self._fetch_bytes(pdf_url)
        if not pdf_bytes:
            logger.warning("Empty PDF for caderno %s on %s", part_code, edition_date)
            return []

        # Cache PDF bytes for storage by the ingestion service
        self.pdf_cache[part_code] = pdf_bytes

        # Parse PDF in a thread (CPU-bound)
        blocks = await self._parse_pdf_bytes(pdf_bytes)

        publications: list[ScrapedPublication] = []
        for block in blocks:
            pub = ScrapedPublication(
                title=block.text[:200].strip() if block.text else None,
                body=block.text,
                section=block.section or part_name,
                organ=block.organ,
                act_type=block.act_type,
                published_at=edition_date,
                page_number=block.page_number,
                pdf_url=pdf_url,
                metadata={
                    "caderno_id": caderno_id,
                    "part_code": part_code,
                    "part_name": part_name,
                },
            )
            publications.append(pub)

        return publications

    async def _parse_pdf_bytes(self, pdf_bytes: bytes) -> list[Any]:
        """Parse PDF bytes using pdfplumber in a thread."""
        import tempfile

        # Write to temp file since pdfplumber needs a file path
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(pdf_bytes)
            tmp_path = Path(tmp.name)

        try:
            blocks = await self._parser.parse(tmp_path)
        finally:
            tmp_path.unlink(missing_ok=True)

        return blocks

    # --- Encoding/decoding helpers ---

    @staticmethod
    def _encode_date(d: date) -> str:
        """Base64-encode a date as YYYYMMDD."""
        raw = d.strftime("%Y%m%d")
        return base64.b64encode(raw.encode("ascii")).decode("ascii")

    @staticmethod
    def _decode_triple_base64(session: str) -> str:
        """Decode a triple-base64 encoded session token.

        The IOERJ site encodes the session parameter as base64(base64(base64(payload))).
        The payload is typically UUID + UNIX_TIMESTAMP.
        """
        decoded = session
        for _ in range(3):
            # Add padding if needed
            padding = 4 - (len(decoded) % 4)
            if padding != 4:
                decoded += "=" * padding
            decoded = base64.b64decode(decoded).decode("ascii", errors="replace")
        return decoded

    @staticmethod
    def _build_pdf_url(uuid_str: str) -> str:
        """Build PDF download URL by inserting 'P' at position 12 of the UUID.

        The IOERJ site expects UUIDs with a 'P' character inserted at index 12.
        Example: '550e8400-e29b-P41d4-a716-446655440000'
        """
        # Remove hyphens for insertion, then reconstruct
        clean = uuid_str.replace("-", "")
        modified = clean[:12] + "P" + clean[12:]

        return f"{BASE_URL}/mostra_edicao.php?k={modified}"

    # --- HTML parsing ---

    @staticmethod
    def _parse_calendar_dates(html: str, year: int, month: int) -> list[date]:
        """Parse the edition selection calendar to find dates with publications.

        Looks for links/anchors that indicate an available edition.
        Active dates typically appear as clickable links with the day number.
        """
        dates: list[date] = []

        # Pattern: look for day links in the calendar HTML
        # The IOERJ calendar uses various patterns for active dates:
        # - <a ...>DD</a> inside calendar cells
        # - onclick handlers with date data
        # - CSS classes indicating active/available dates
        day_patterns = [
            # Links with day numbers (most common pattern)
            re.compile(r'<a[^>]*?data=["\']?([^"\'>\s]+)["\']?[^>]*>(\d{1,2})</a>', re.IGNORECASE),
            # onclick with encoded date
            re.compile(
                r'onclick=["\'].*?data=([A-Za-z0-9+/=]+).*?["\']',
                re.IGNORECASE,
            ),
            # Simple linked days in calendar cells
            re.compile(
                r'<td[^>]*class=["\'][^"\']*ativo[^"\']*["\'][^>]*>\s*(\d{1,2})\s*</td>',
                re.IGNORECASE,
            ),
        ]

        # Try each pattern
        for pattern in day_patterns:
            for match in pattern.finditer(html):
                groups = match.groups()
                day_str = groups[-1] if groups else None
                if day_str and day_str.isdigit():
                    day = int(day_str)
                    if 1 <= day <= 31:
                        try:
                            dates.append(date(year, month, day))
                        except ValueError:
                            continue

        # Fallback: look for any linked day numbers inside table cells
        if not dates:
            cell_pattern = re.compile(
                r"<td[^>]*>\s*<a[^>]*>\s*(\d{1,2})\s*</a>\s*</td>",
                re.IGNORECASE,
            )
            for match in cell_pattern.finditer(html):
                day = int(match.group(1))
                if 1 <= day <= 31:
                    try:
                        dates.append(date(year, month, day))
                    except ValueError:
                        continue

        return sorted(set(dates))

    @staticmethod
    def _parse_cadernos(html: str) -> list[tuple[int, str]]:
        """Extract caderno IDs and session tokens from the edition page HTML.

        Returns list of (caderno_id, session_token) tuples.
        """
        cadernos: list[tuple[int, str]] = []

        # Pattern: links to mostra_edicao.php with session parameter
        session_pattern = re.compile(
            r'mostra_edicao\.php\?session=([A-Za-z0-9+/=]+)',
            re.IGNORECASE,
        )

        # Also look for caderno identifiers near the session links
        # The HTML typically has caderno names/ids associated with each session link
        block_pattern = re.compile(
            r'(?:jornal|caderno|parte)[^\d]*(\d{1,2})[^<]*<[^>]*'
            r'mostra_edicao\.php\?session=([A-Za-z0-9+/=]+)',
            re.IGNORECASE | re.DOTALL,
        )

        for match in block_pattern.finditer(html):
            caderno_id = int(match.group(1))
            session_token = match.group(2)
            cadernos.append((caderno_id, session_token))

        # If block pattern didn't work, try just finding session tokens
        if not cadernos:
            for match in session_pattern.finditer(html):
                session_token = match.group(1)
                # Try to find associated caderno ID by looking at surrounding text
                start = max(0, match.start() - 500)
                context = html[start : match.start()]

                # Look for caderno ID in the context
                id_match = re.search(r'(?:jornal|id)[=:]\s*["\']?(\d{1,2})', context, re.IGNORECASE)
                if id_match:
                    caderno_id = int(id_match.group(1))
                else:
                    # Assign sequential ID if we can't determine the real one
                    caderno_id = len(cadernos)

                cadernos.append((caderno_id, session_token))

        return cadernos

    # --- HTTP helpers ---

    async def _fetch_text(self, url: str) -> str:
        """Fetch URL and return response text with retry logic."""
        client = await self._get_client()
        last_error: Exception | None = None

        for attempt in range(_MAX_RETRIES):
            try:
                response = await client.get(url)
                response.raise_for_status()
                # Handle encoding - IOERJ uses PHP 5.3/IIS, likely latin-1
                content_type = response.headers.get("content-type", "")
                if "charset" not in content_type.lower():
                    # Try to decode as latin-1 if UTF-8 fails
                    try:
                        return response.content.decode("utf-8")
                    except UnicodeDecodeError:
                        return response.content.decode("latin-1")
                return response.text
            except httpx.HTTPStatusError as exc:
                last_error = exc
                logger.warning(
                    "HTTP %d fetching %s (attempt %d/%d)",
                    exc.response.status_code,
                    url,
                    attempt + 1,
                    _MAX_RETRIES,
                )
            except httpx.HTTPError as exc:
                last_error = exc
                logger.warning(
                    "HTTP error fetching %s (attempt %d/%d): %s",
                    url,
                    attempt + 1,
                    _MAX_RETRIES,
                    exc,
                )

            if attempt < _MAX_RETRIES - 1:
                delay = _RETRY_BACKOFF_BASE * (2**attempt)
                await asyncio.sleep(delay)

        msg = f"Failed to fetch {url} after {_MAX_RETRIES} attempts"
        raise httpx.HTTPError(msg) from last_error

    async def _fetch_bytes(self, url: str) -> bytes:
        """Fetch URL and return raw bytes with retry logic."""
        client = await self._get_client()
        last_error: Exception | None = None

        for attempt in range(_MAX_RETRIES):
            try:
                response = await client.get(url)
                response.raise_for_status()
                return response.content
            except httpx.HTTPStatusError as exc:
                last_error = exc
                logger.warning(
                    "HTTP %d fetching PDF %s (attempt %d/%d)",
                    exc.response.status_code,
                    url,
                    attempt + 1,
                    _MAX_RETRIES,
                )
            except httpx.HTTPError as exc:
                last_error = exc
                logger.warning(
                    "HTTP error fetching PDF %s (attempt %d/%d): %s",
                    url,
                    attempt + 1,
                    _MAX_RETRIES,
                    exc,
                )

            if attempt < _MAX_RETRIES - 1:
                delay = _RETRY_BACKOFF_BASE * (2**attempt)
                await asyncio.sleep(delay)

        msg = f"Failed to fetch PDF {url} after {_MAX_RETRIES} attempts"
        raise httpx.HTTPError(msg) from last_error
