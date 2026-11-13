"""Declaraciones de operaciones de los miembros de la Camara de EE. UU. (PTR).

Fuente oficial y gratuita: el Clerk of the House publica
- un indice anual en XML (``{year}FD.zip`` con ``{year}FD.xml``): cada fila es
  una declaracion con apellido, nombre, estado+distrito, tipo, fecha de
  presentacion y DocID. Tipo ``P`` = Periodic Transaction Report (STOCK Act).
- cada PTR en PDF (``ptr-pdfs/{year}/{DocID}.pdf``). Los presentados por la
  web (DocID que empieza por 2) son PDF de texto y se leen sin OCR; los de
  papel (8xxxxxxx, 9xxxxxxx) son escaneos de una cuadricula marcada a mano:
  probado con el OCR local (tesseract), las X de la columna de importe no se
  leen de forma fiable, asi que se guarda la declaracion (quien, cuando,
  enlace) sin inventar filas.

Hosts fijos (disclosures-clerk.house.gov), sin URLs del usuario. Peticiones
lentas y con User-Agent de contacto. Nada de modelo: el parseo es regex sobre
el texto del PDF y lo que no casa con la forma de una fila no se inventa.

Aviso legal (5 U.S.C. §13107): estas declaraciones no pueden usarse con fines
comerciales salvo para su difusion al publico general.
"""

from __future__ import annotations

import io
import re
import threading
import time
import zipfile
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import httpx
from defusedxml import ElementTree as DefusedET

from app.core.config import get_settings

BASE = "https://disclosures-clerk.house.gov/public_disc"
INDEX_URL = BASE + "/financial-pdfs/{year}FD.zip"
PTR_URL = BASE + "/ptr-pdfs/{year}/{doc_id}.pdf"
PARSER_VERSION = "1.0"
MIN_INTERVAL_SECONDS = 0.5
STOCK_ACT_DUE_DAYS = 45

_lock = threading.Lock()
_last_request = 0.0


def _throttle() -> None:
    global _last_request
    with _lock:
        wait = MIN_INTERVAL_SECONDS - (time.monotonic() - _last_request)
        if wait > 0:
            time.sleep(wait)
        _last_request = time.monotonic()


def _headers() -> dict[str, str]:
    return {"User-Agent": get_settings().sec_user_agent}


def _get(url: str, client: httpx.Client | None = None) -> bytes:
    _throttle()
    if client is not None:
        response = client.get(url, headers=_headers())
    else:
        with httpx.Client(timeout=60, headers=_headers(), follow_redirects=False) as owned:
            response = owned.get(url)
    response.raise_for_status()
    return response.content


def _iso(us_date: str | None) -> str | None:
    if not us_date:
        return None
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(us_date.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


# --- indice anual -----------------------------------------------------------

def parse_index_xml(xml: str | bytes) -> list[dict[str, Any]]:
    """Filas PTR (FilingType P) del indice anual, en el orden del fichero."""
    root = DefusedET.fromstring(xml)
    out: list[dict[str, Any]] = []
    for member in root.findall("Member"):
        if (member.findtext("FilingType") or "").strip() != "P":
            continue
        doc_id = (member.findtext("DocID") or "").strip()
        if not doc_id.isdigit():
            continue
        year = (member.findtext("Year") or "").strip()
        sd = (member.findtext("StateDst") or "").strip().upper()
        out.append({
            "doc_id": doc_id,
            "year": int(year) if year.isdigit() else None,
            "last": (member.findtext("Last") or "").strip(),
            "first": (member.findtext("First") or "").strip(),
            "prefix": (member.findtext("Prefix") or "").strip(),
            "suffix": (member.findtext("Suffix") or "").strip(),
            "state_district": sd,
            "state": sd[:2] or None,
            "district": sd[2:] or None,
            "filing_date": _iso(member.findtext("FilingDate")),
            "electronic": doc_id.startswith("2"),
        })
    return out


def fetch_index(year: int, client: httpx.Client | None = None) -> list[dict[str, Any]]:
    data = _get(INDEX_URL.format(year=year), client)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        name = next(n for n in archive.namelist() if n.lower().endswith(".xml"))
        rows = parse_index_xml(archive.read(name))
    for row in rows:
        row["year"] = row["year"] or year
        row["source_url"] = PTR_URL.format(year=row["year"], doc_id=row["doc_id"])
    return rows


def fetch_ptr_pdf(year: int, doc_id: str, client: httpx.Client | None = None) -> bytes:
    if not str(doc_id).isdigit():
        raise ValueError("DocID no numerico")
    return _get(PTR_URL.format(year=int(year), doc_id=doc_id), client)


# --- texto del PDF ------------------------------------------------------------

def pdf_text(pdf: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(pdf))
    # Las etiquetas de la plantilla del Clerk salen con NUL en vez de letras
    # («F\x00\x00 S\x00: New»): se tratan como espacios.
    return "\n".join((page.extract_text() or "") for page in reader.pages).replace("\x00", " ")


# --- filas ----------------------------------------------------------------------

TYPE_LABELS = {"P": "compra", "S": "venta", "S (partial)": "venta_parcial", "E": "canje"}

_META_LINE = re.compile(r"^\s*([A-Z])(?:\s+([A-Z]))?\s+:\s*")
# Descripcion (D) y comentarios (C) pueden partirse en varias lineas: lo que
# sigue a uno de ellos hasta la proxima fila es su continuacion, no un activo.
_FREE_TEXT_META = {("D", None), ("C", None)}
_SENTENCE_END = re.compile(r"(?<!\bInc)(?<!\bCorp)(?<!\bCo)(?<!\bLtd)(?<!\bPlc)(?<!\bN\.V)(?<!\bS\.A)(?<!\bL\.P)\.\s+(?=[A-Z])")
_OWNER_START = re.compile(r"^\s*(?:SP|JT|DC)\s+\S")
_HEADER_START = re.compile(r"^ID Owner Asset Transaction")
_ROW = re.compile(
    r"^(?:(?P<owner>SP|JT|DC)\s+)?(?P<asset>.*?)\s*\[(?P<atype>[A-Z0-9]{2})\]\s*"
    r"(?P<type>P|S\s*\(partial\)|S|E)\s+"
    r"(?P<tdate>\d{1,2}/\d{1,2}/\d{4})\s+(?P<ndate>\d{1,2}/\d{1,2}/\d{4})\s+"
    r"(?P<amount>(?:Spouse/DC\s+)?Over\s+\$[\d,]+|\$[\d,]+\s*-\s*\$[\d,]+|\$[\d,]+(?:\.\d{1,2})?(?![\d,.]*\s*-))",
)
_TICKER = re.compile(r"\(([A-Z][A-Z0-9.\-/]{0,9})\)")
_NAME = re.compile(r"^Name:\s*(?:Hon\.\s*)?(.+?)\s*$", re.M)
_STATUS = re.compile(r"^Status:\s*(.+?)\s*$", re.M)
_SD = re.compile(r"^State/District:\s*([A-Z]{2}\d{0,2})\s*$", re.M)
_SIGNED = re.compile(r"Digitally Signed:\s*.+?,\s*(\d{1,2}/\d{1,2}/\d{4})")
_FILING_ID = re.compile(r"Filing ID #(\d+)")


def parse_amount(text: str) -> dict[str, Any]:
    clean = re.sub(r"\s+", " ", text.strip())
    over = re.search(r"Over \$([\d,]+)", clean)
    if over:
        low = int(over.group(1).replace(",", "")) + 1
        return {"amount_text": clean, "amount_min": low, "amount_max": None}
    rng = re.match(r"\$([\d,]+)\s*-\s*\$([\d,]+)", clean)
    if rng:
        low, high = (int(rng.group(i).replace(",", "")) for i in (1, 2))
        if low > high:
            return {"amount_text": clean, "amount_min": None, "amount_max": None}
        return {"amount_text": clean, "amount_min": low, "amount_max": high}
    exact = re.fullmatch(r"\$([\d,]+)(?:\.(\d{1,2}))?", clean)
    if exact:
        # Algunos miembros declaran la cifra exacta en vez del rango.
        whole = int(exact.group(1).replace(",", ""))
        return {"amount_text": clean, "amount_min": whole, "amount_max": whole + (1 if int(exact.group(2) or "0") else 0)}
    return {"amount_text": clean, "amount_min": None, "amount_max": None}


def _transaction_lines(text: str) -> list[str]:
    """Lineas de la tabla de operaciones, sin cabeceras de pagina ni metadatos."""
    lines = text.splitlines()
    out: list[str] = []
    in_table = False
    in_header = False
    for line in lines:
        stripped = line.strip()
        if _HEADER_START.match(stripped):
            in_table = True
            in_header = True
            continue
        if in_header:
            if stripped.startswith("$200?"):
                in_header = False
            continue
        if not in_table:
            continue
        if stripped.startswith("* For the complete list"):
            break
        if not stripped or stripped.startswith("Filing ID #"):
            continue
        out.append(stripped)
    return out


def parse_ptr_text(text: str) -> dict[str, Any]:
    """Cabecera y filas de un PTR electronico (texto de pypdf)."""
    name = _NAME.search(text)
    status = _STATUS.search(text)
    sd = _SD.search(text)
    signed = _SIGNED.search(text)
    filing_id = _FILING_ID.search(text)
    trades: list[dict[str, Any]] = []
    buffer: list[str] = []
    unparsed = 0
    after_free_text = False
    for line in _transaction_lines(text):
        meta = _META_LINE.match(line)
        if meta:
            if buffer and not after_free_text:
                unparsed += 1
            buffer = []
            # Cualquier campo (D, C, S O...) puede partirse en varias lineas.
            after_free_text = True
            continue
        if after_free_text and _OWNER_START.match(line):
            # Un titular explicito SP/JT/DC abre una fila nueva, aunque su
            # importe no se pueda leer. Lo anterior era cola del comentario.
            buffer = []
            after_free_text = False
        buffer.append(line)
        joined = re.sub(r"\s+", " ", " ".join(buffer))
        match = _ROW.match(joined)
        if not match:
            continue
        trimmed = False
        if after_free_text and len(buffer) > 1:
            # Si la fila real empieza con su titular (SP/JT/DC) mas abajo, lo
            # anterior es la cola del campo partido del bloque previo.
            for start in range(1, len(buffer)):
                if _OWNER_START.match(buffer[start]):
                    tail = _ROW.match(re.sub(r"\s+", " ", " ".join(buffer[start:])))
                    if tail:
                        match, trimmed = tail, True
                    break
        asset = match.group("asset").strip(" -")
        if after_free_text and not trimmed:
            # La cola de una descripcion partida quedo delante del activo:
            # se corta en el ultimo punto de frase (no en «Inc.», «Corp.»...).
            cut = list(_SENTENCE_END.finditer(asset))
            if cut:
                asset = asset[cut[-1].end():].strip()
        after_free_text = False
        tickers = _TICKER.findall(asset)
        tx_type = re.sub(r"\s+", " ", match.group("type"))
        trades.append({
            "owner": match.group("owner") or "self",
            "asset": asset,
            "asset_type": match.group("atype"),
            "ticker": tickers[-1] if tickers else None,
            "type": tx_type,
            "type_label": TYPE_LABELS.get(tx_type, "otra"),
            "tx_date": _iso(match.group("tdate")),
            "notification_date": _iso(match.group("ndate")),
            **parse_amount(match.group("amount")),
        })
        buffer = []
    # La ultima fila tambien cuenta aunque no haya otro metadato que cierre
    # su bloque. Las continuaciones de comentarios no son operaciones.
    if buffer and not after_free_text:
        unparsed += 1
    return {
        "member": name.group(1).strip() if name else None,
        "status": status.group(1).strip() if status else None,
        "state_district": sd.group(1) if sd else None,
        "signed_date": _iso(signed.group(1)) if signed else None,
        "filing_id": filing_id.group(1) if filing_id else None,
        "trades": trades,
        "unparsed_blocks": unparsed,
    }


def days_late(tx_date: str | None, filed: str | None) -> int | None:
    """Dias por encima de los 45 del STOCK Act (0 = a tiempo; None sin fechas)."""
    if not tx_date or not filed:
        return None
    try:
        gap = (date.fromisoformat(filed) - date.fromisoformat(tx_date)).days
    except (TypeError, ValueError):
        return None
    if gap < 0:
        return None
    return max(0, gap - STOCK_ACT_DUE_DAYS)


def amount_midpoint(trade: dict[str, Any]) -> Decimal | None:
    low, high = trade.get("amount_min"), trade.get("amount_max")
    if low is None:
        return None
    if high is None:
        return Decimal(low)
    return (Decimal(low) + Decimal(high)) / 2
