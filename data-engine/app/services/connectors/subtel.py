"""Official, free SUBTEL register for the verified AST Chile request.

Request date is NOT decree date or Diario Oficial publication date. Polling
this tracked request detects its updates; it is not an exhaustive Chile crawl.
"""
from __future__ import annotations

import io
import re
from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
from pypdf import PdfReader

HOST = "publico.subtel.gob.cl"
REGISTER = f"https://{HOST}/data-externa/getSolicitudes"
PARAMS = {"tipoServicio": "SI", "fechaDesde": "28/01/2026", "fechaHasta": "28/01/2026"}
REGISTER_URL = REGISTER + "?" + urlencode(PARAMS)
MAX_BYTES = 5_000_000


class _Rows(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.cells = None
        self.cell = None
        self.paths = []

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.cells, self.paths = [], []
        elif tag == "td" and self.cells is not None:
            self.cell = []
        elif tag == "button" and self.cells is not None:
            path = dict(attrs).get("path")
            if path:
                self.paths.append(path)

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag == "td" and self.cell is not None:
            self.cells.append(" ".join(" ".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.cells is not None:
            self.rows.append((self.cells, self.paths))
            self.cells = None


def official_pdf_url(value: str) -> str:
    """Only the observed SUBTEL download endpoint and exempt-decree path.

    The register still links tramites, which returned 404. Its public alias
    was independently verified. No arbitrary URL or redirect is accepted.
    """
    url = urlsplit(value)
    if (url.scheme != "https" or url.netloc not in (HOST, "tramites.subtel.gob.cl")
            or url.path != "/dwldDocSubtel/view" or url.fragment):
        raise ValueError("Untrusted SUBTEL document URL")
    query = parse_qs(url.query, strict_parsing=True)
    paths = query.get("rutaArchivo", [])
    if (set(query) != {"rutaArchivo"} or len(paths) != 1
            or not re.fullmatch(r"/ofpartes/Decretos/Exentos/20\d{2}/\d{2}de_\d+\.pdf", paths[0])):
        raise ValueError("Invalid SUBTEL decree path")
    return f"https://{HOST}{url.path}?" + urlencode(query, doseq=True)


def parse_register(html: str) -> list[dict]:
    parser = _Rows()
    parser.feed(html)
    results = []
    for cells, paths in parser.rows:
        if not cells or not re.fullmatch(r"AST SpaceMobile Chile SpA Servicios Intermedios", cells[0], re.I):
            continue
        if len(cells) != 7 or "Otorga Concesión" not in cells[1] or "Nro: 10872" not in cells[1]:
            continue
        match = re.fullmatch(r"Número: (\d+) Fecha: (\d{2}/\d{2}/\d{4})", cells[6])
        if not match:
            continue  # A pending application is not an issued decree.
        date = datetime.strptime(match[2], "%d/%m/%Y").date()
        for path in paths:
            try:
                pdf_url = official_pdf_url(path)
            except ValueError:
                continue
            filename = parse_qs(urlsplit(pdf_url).query)["rutaArchivo"][0]
            if not filename.endswith(f"/{str(date.year)[2:]}de_{match[1]}.pdf"):
                continue
            results.append({"issuer": "AST SpaceMobile Chile SpA", "request_number": 10872,
                            "request_date": "2026-01-28", "decree_number": int(match[1]),
                            "decree_date": date.isoformat(), "pdf_url": pdf_url,
                            "register_url": REGISTER_URL, "publication_date": None})
    return results


async def _download(client: httpx.AsyncClient, url: str) -> bytes:
    async with client.stream("GET", url, follow_redirects=False) as response:
        response.raise_for_status()
        if response.is_redirect:
            raise ValueError("SUBTEL redirects are not accepted")
        chunks, size = [], 0
        async for chunk in response.aiter_bytes():
            size += len(chunk)
            if size > MAX_BYTES:
                raise ValueError("SUBTEL response too large")
            chunks.append(chunk)
        return b"".join(chunks)


async def fetch_decrees(client: httpx.AsyncClient | None = None) -> list[dict]:
    if client is None:
        async with httpx.AsyncClient(timeout=30, headers={"User-Agent": "GerarAI/1.0 official regulatory research"}) as own:
            return await fetch_decrees(own)
    html = (await _download(client, REGISTER_URL)).decode("utf-8")
    if "<table" not in html.lower():
        raise ValueError("Invalid SUBTEL register")
    results = parse_register(html)
    for row in results:
        content = await _download(client, row["pdf_url"])
        if not content.startswith(b"%PDF-"):
            raise ValueError("SUBTEL document is not PDF")
        reader = PdfReader(io.BytesIO(content))
        if len(reader.pages) > 20:
            raise ValueError("Unexpected SUBTEL decree size")
        text = " ".join(" ".join(page.extract_text() or "" for page in reader.pages).split())
        if (not re.search(r"AST\s+SPACEMOBILE\s+CHILE\s+SpA", text, re.I)
                or "10.872" not in text or "Servicio Intermedio" not in text):
            raise ValueError("SUBTEL decree issuer/request mismatch")
        row["text"] = text
        import hashlib
        row["sha256"] = hashlib.sha256(content).hexdigest()
    return results
