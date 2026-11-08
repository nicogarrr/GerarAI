"""Anexos que SON el informe anual: 40-F (EX-99.x) y 10-K (EX-13).

Caso real (cartera de Nico, 8-nov-2026): Brookfield Corporation (BN) presenta
un 40-F (sistema multijurisdiccional EE. UU.-Canada). El documento principal
(``bn-20251231.htm``) es la portada y la lista de anexos; el informe anual
con los estados financieros, el MD&A y la informacion por segmentos va en
EX-99.2 (``bn-20251231_d2.htm``, 6,5 MB) y el AIF en EX-99.1 (1,3 MB). La
tesis solo pedia el texto del documento principal, asi que el desglose por
partes de los expertos rechazaba BN: «sin ingresos por segmento».

Lo mismo pasa con muchos 10-K que incorporan por referencia el informe a los
accionistas (EX-13, habitual en bancos y aseguradoras).

Regla general (nunca por emisor): del indice oficial del filing
(``<accession>-index.html``) se toman los anexos EX-99.x / EX-13.x en
htm/html/pdf de al menos ``MIN_EXHIBIT_BYTES`` (certificaciones, consentimientos
del auditor y cartas pesan 3-12 KB). El tipo y el tamano los declara el
indice de la SEC; nada se adivina por el nombre del fichero.
"""

from __future__ import annotations

import re
from typing import Any

ANNUAL_WITH_EXHIBIT_REPORT = frozenset({"40-F", "40-F/A", "10-K", "10-K/A"})
MIN_EXHIBIT_BYTES = 100_000
MAX_EXHIBITS = 3
_TYPE_RE = re.compile(r"^EX-(99|13)(\.\d+)?$", re.IGNORECASE)
_NAME_RE = re.compile(r"^[A-Za-z0-9._\-]+\.(htm|html|pdf)$", re.IGNORECASE)


def _cell_text(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value).replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", text).strip()


def parse_report_exhibits(index_html: str) -> list[dict[str, Any]]:
    """[{type, filename, size, description}] de los anexos que pueden ser el informe.

    Filas del indice: Seq | Description | Document | Type | Size."""
    out: list[dict[str, Any]] = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", index_html or "", re.S | re.IGNORECASE):
        cells = [_cell_text(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S | re.IGNORECASE)]
        if len(cells) < 5:
            continue
        ex_type = cells[3].upper()
        filename = cells[2].split(" ")[0] if cells[2] else ""
        if not _TYPE_RE.match(ex_type) or not _NAME_RE.match(filename):
            continue
        try:
            size = int(cells[4].replace(",", ""))
        except ValueError:
            continue
        if size < MIN_EXHIBIT_BYTES:
            continue
        out.append({"type": ex_type, "filename": filename, "size": size, "description": cells[1]})
    # Mayor primero: el informe anual completo pesa mas que el AIF o una carta.
    out.sort(key=lambda e: e["size"], reverse=True)
    return out[:MAX_EXHIBITS]


def index_page_url(filing: dict[str, Any]) -> str | None:
    """``<index_url><accession>-index.html`` del filing (forma de ``recent_filings``)."""
    base = str(filing.get("index_url") or "")
    accession = str(filing.get("accession_number") or "")
    if not base or not re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession):
        return None
    return f"{base.rstrip('/')}/{accession}-index.html"


async def fetch_report_exhibits(filing: dict[str, Any]) -> list[dict[str, Any]]:
    """Anexos-informe del filing con su URL absoluta (una peticion a sec.gov)."""
    import httpx

    from app.services.connectors.sec_edgar import default_headers
    from app.services.connectors.sec_pacing import pacer

    if str(filing.get("form") or "").upper() not in ANNUAL_WITH_EXHIBIT_REPORT:
        return []
    url = index_page_url(filing)
    if url is None:
        return []
    await pacer.wait()
    async with httpx.AsyncClient(timeout=30.0, headers=default_headers()) as client:
        resp = await client.get(url)
        resp.raise_for_status()
    base = str(filing["index_url"]).rstrip("/") + "/"
    return [{**ex, "url": base + ex["filename"]} for ex in parse_report_exhibits(resp.text)]
