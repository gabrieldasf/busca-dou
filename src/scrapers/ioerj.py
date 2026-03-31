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

BASE_URL = "http://www.ioerj.com.br/portal/modules/conteudoonline"

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
            # Initialize session by visiting the calendar page (gets PHPSESSID cookie)
            await self._client.get(f"{BASE_URL}/do_seleciona_data.php")
        return self._client

    async def close(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    # --- Public interface ---

    async def list_available_dates(self, year: int, month: int) -> list[date]:
        """Return dates with published editions for the given month.

        Requests the calendar page and parses links to find dates
        with published editions.
        """
        url = f"{BASE_URL}/do_seleciona_data.php"

        html = await self._fetch_text(url)
        return self._parse_calendar_dates(html, year, month)

    async def scrape_edition(self, edition_date: date) -> list[ScrapedPublication]:
        """Scrape all cadernos for a given edition date.

        The IOERJ site serves the full edition as a single PDF (all cadernos
        concatenated). We download it once via the first caderno's viewer,
        then parse and tag publications with their caderno info.
        """
        encoded = self._encode_date(edition_date)
        url = f"{BASE_URL}/do_seleciona_edicao.php?data={encoded}"

        html = await self._fetch_text(url)
        cadernos = self._parse_cadernos(html)

        if not cadernos:
            logger.warning("No cadernos found for date %s", edition_date)
            return []

        # Download the edition PDF once (all cadernos share the same PDF)
        first_caderno_id, first_session = cadernos[0]
        try:
            publications = await self._scrape_caderno(
                edition_date, first_caderno_id, first_session,
            )
        except Exception:
            logger.exception("Failed to scrape edition for %s", edition_date)
            return []

        # Tag the edition with all available caderno names
        caderno_names = [
            CADERNOS.get(cid, (str(cid), "Desconhecido"))[1]
            for cid, _ in cadernos
        ]

        logger.info(
            "Scraped %d publications from %s (cadernos: %s)",
            len(publications),
            edition_date,
            ", ".join(caderno_names),
        )
        return publications

    # --- Caderno scraping ---

    async def _scrape_caderno(
        self,
        edition_date: date,
        caderno_id: int,
        session_token: str,
    ) -> list[ScrapedPublication]:
        """Download and parse a single caderno PDF.

        Flow:
        1. Visit viewer page (mostra_edicao.php?session=TOKEN) to trigger
           server-side PDF generation
        2. Download the generated PDF from include/pdfjs/web/tmp.pdf
        """
        part_code, part_name = CADERNOS.get(caderno_id, (str(caderno_id), "Desconhecido"))

        logger.info("Downloading caderno %s (%s) for %s", part_code, part_name, edition_date)

        # Visit viewer page - this prepares server-side PDF generation
        viewer_url = f"{BASE_URL}/mostra_edicao.php?session={session_token}"
        viewer_html = await self._fetch_text(viewer_url)

        # Extract pd variable (UUID) from viewer page
        pd_match = re.search(r'var\s+pd\s*=\s*["\']([^"\']+)["\']', viewer_html)
        if not pd_match:
            logger.warning("No pd variable found for caderno %s on %s", part_code, edition_date)
            return []

        pd_uuid = pd_match.group(1)

        # Download the PDF - IOERJ serves the current edition's PDF
        # at a static path after visiting the viewer
        pdf_url = f"{BASE_URL}/include/pdfjs/web/tmp.pdf"
        pdf_bytes = await self._fetch_bytes(pdf_url)
        if not pdf_bytes or not pdf_bytes.startswith(b"%PDF"):
            logger.warning("Invalid PDF for caderno %s on %s", part_code, edition_date)
            return []

        logger.info(
            "Downloaded %d bytes for caderno %s (%s) [pd=%s]",
            len(pdf_bytes), part_code, part_name, pd_uuid[:8],
        )

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
        """Parse the calendar page to find dates with published editions.

        Links follow the pattern:
        <a href="do_seleciona_edicao.php?data=BASE64">DD</a>
        where BASE64 decodes to YYYYMMDD.
        """
        dates: list[date] = []

        # Match links to do_seleciona_edicao.php with base64 data param
        pattern = re.compile(
            r'do_seleciona_edicao\.php\?data=([A-Za-z0-9+/=]+)["\'][^>]*>(\d{1,2})<',
            re.IGNORECASE,
        )

        for match in pattern.finditer(html):
            b64_data = match.group(1)
            # Decode base64 to verify the year/month match
            try:
                decoded = base64.b64decode(b64_data).decode("ascii")
                decoded_year = int(decoded[:4])
                decoded_month = int(decoded[4:6])
                decoded_day = int(decoded[6:8])
                if decoded_year == year and decoded_month == month:
                    dates.append(date(year, month, decoded_day))
            except (ValueError, IndexError):
                # Fallback: use the day number from the link text
                day = int(match.group(2))
                if 1 <= day <= 31:
                    try:
                        dates.append(date(year, month, day))
                    except ValueError:
                        continue

        return sorted(set(dates))

    @staticmethod
    def _parse_cadernos(html: str) -> list[tuple[int, str]]:
        """Extract caderno IDs and session tokens from the edition page HTML.

        The HTML follows the pattern:
        <a href="mostra_edicao.php?session=TOKEN">Parte I (Poder Executivo)</a>

        Returns list of (caderno_id, session_token) tuples.
        """
        cadernos: list[tuple[int, str]] = []

        # Match: session token + link text containing part name
        pattern = re.compile(
            r'mostra_edicao\.php\?session=([A-Za-z0-9+/=]+)[^>]*>([^<]+)</a>',
            re.IGNORECASE,
        )

        # Map part names from HTML text to caderno IDs
        part_name_to_id: dict[str, int] = {
            "I": 12, "IA": 1, "IB": 2, "I DPGE": 13, "I JC": 20,
            "II": 3, "III-E": 6, "III-F": 7, "IV": 5, "V": 4,
            "DO Campos": 18,
        }

        for match in pattern.finditer(html):
            session_token = match.group(1)
            link_text = match.group(2).strip()

            # Extract part code from link text like "Parte I (Poder Executivo)"
            part_match = re.search(r"Parte\s+([\w\s-]+?)(?:\s*[\(-]|$)", link_text)
            if part_match:
                part_code = part_match.group(1).strip()
                caderno_id = part_name_to_id.get(part_code, len(cadernos))
            else:
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
