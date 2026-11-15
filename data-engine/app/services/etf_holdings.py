"""Holdings oficiales de ETFs tematicos (UFO, NASA, JEDI) para la tira de noticias.

Fuente: el fichero publicado por el propio emisor (Procure, Tema: CSV descubierto
en la pagina del fondo, la URL lleva la fecha; VanEck: Excel de descarga fija). Solo se guardan tickers de renta
variable con peso y fecha de corte del fichero. Si la descarga o el parseo
falla, o el fichero parece incompleto, se conserva la carga anterior (nunca se
borra por un fallo). Sin LLM, coste 0, una descarga por ETF y semana."""

from __future__ import annotations

import csv
import io
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

import httpx
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models.entities import EtfHolding

logger = logging.getLogger(__name__)

MIN_WEIGHT_PCT = Decimal("2")  # peso minimo para vincular una noticia a un ETF
MAX_AGE_DAYS = 45
MIN_ROWS = 10
# Fixed ingestion budgets. Reject oversize input; never truncate a snapshot.
MAX_DOWNLOAD_BYTES = 2 * 1024 * 1024
MAX_XLSX_ENTRIES = 64
MAX_XLSX_MEMBER_BYTES = 4 * 1024 * 1024
MAX_XLSX_TOTAL_BYTES = 8 * 1024 * 1024
MAX_XLSX_COMPRESSION_RATIO = 100
MAX_XLSX_ROWS = 10_000
_TICKER = re.compile(r"^[A-Z]{1,5}$")


@dataclass(frozen=True)
class EtfSource:
    etf: str
    name: str
    page: str
    link_re: str
    direct_url: str | None = None  # descarga fija (VanEck): sin descubrimiento en la pagina
    binary: bool = False  # el parser recibe bytes (xlsx) en vez de texto


SOURCES = {
    "UFO": EtfSource("UFO", "Procure Space ETF", "https://procureetfs.com/ufo/",
                     r"https://procureetfs\.com/[^\"' ]*UFO[^\"' ]*Holdings[^\"' ]*\.csv"),
    "NASA": EtfSource("NASA", "Tema Space Innovators ETF", "https://temaetfs.com/nasa",
                      r"https://temaetfs\.com/[^\"' ]*NASA-holdings-\d+\.csv"),
    # UCITS de VanEck: el Excel «All Holdings» es publico; la web exige las
    # cookies de pais que fija su primera redireccion (?cken=true), por eso el
    # cliente httpx comparte cookies entre peticiones.
    "JEDI": EtfSource("JEDI", "VanEck Space Innovators UCITS ETF",
                      "https://www.vaneck.com/uk/en/investments/space-etf/holdings/", "",
                      direct_url="https://www.vaneck.com/uk/en/investments/space-etf/downloads/holdings/",
                      binary=True),
}


def _pct(raw: str | None, *, fraction: bool) -> Decimal | None:
    try:
        value = Decimal((raw or "").strip().rstrip("%").replace(",", ""))
    except InvalidOperation:
        return None
    if not value.is_finite() or value < 0 or value > (1 if fraction else 100):
        return None
    return value * 100 if fraction else value


def parse_procure(text: str) -> tuple[date | None, list[tuple[str, Decimal]]]:
    rows: list[tuple[str, Decimal]] = []
    as_of: date | None = None
    for rec in csv.DictReader(io.StringIO(text.lstrip("\ufeff"))):
        ticker = (rec.get("StockTicker") or "").strip().upper()
        weight = _pct(rec.get("Weightings"), fraction=False)
        if not _TICKER.match(ticker):
            continue
        try:
            day = datetime.strptime((rec.get("Date") or "").strip(), "%m/%d/%Y").date()
        except ValueError as exc:
            raise ValueError("ETF invalid equity date") from exc
        if weight is None:
            raise ValueError("ETF invalid equity weight")
        if as_of is not None and as_of != day:
            raise ValueError("ETF mixed snapshot dates")
        as_of = day
        rows.append((ticker, weight))
    return as_of, rows


def parse_tema(text: str) -> tuple[date | None, list[tuple[str, Decimal]]]:
    rows: list[tuple[str, Decimal]] = []
    as_of: date | None = None
    for rec in csv.DictReader(io.StringIO(text.lstrip("\ufeff"))):
        ticker = (rec.get("ticker") or "").strip().upper()
        weight = _pct(rec.get("percent_of_nav"), fraction=True)
        if (rec.get("is_cash") or "0").strip() not in ("0", ""):
            continue
        # Solo cotizadas en EEUU con CUSIP (excluye «SPACEX SPV», «FTC LN», «3491 TT»).
        if not _TICKER.match(ticker) or not (rec.get("cusip") or "").strip():
            continue
        if (rec.get("country") or "").strip() != "United States":
            continue
        try:
            day = datetime.strptime((rec.get("holdings_date") or "").strip(), "%Y-%m-%d").date()
        except ValueError as exc:
            raise ValueError("ETF invalid equity date") from exc
        if weight is None:
            raise ValueError("ETF invalid equity weight")
        if as_of is not None and as_of != day:
            raise ValueError("ETF mixed snapshot dates")
        as_of = day
        rows.append((ticker, weight))
    return as_of, rows


_XLSX_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_JEDI_DATE = re.compile(r"All Holdings\s+(\d{1,2}/\d{1,2}/\d{4})")
_JEDI_TICKER = re.compile(r"^([A-Z]{1,5}) US$")
_ISIN = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")
_CELL_REF = re.compile(r"^([A-Z]{1,2})([1-9][0-9]*)$")
_JEDI_COLUMNS = ["Number", "Holding Name", "Ticker", "ISIN", "Shares", "Market Value", "% of Net Assets"]


def _download_bytes(http: httpx.Client, url: str) -> bytes:
    """Bound streamed bodies, including redirects (httpx otherwise drains them)."""
    for _ in range(6):
        with http.stream("GET", url, headers={"Accept-Encoding": "identity"}, follow_redirects=False) as response:
            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    raise ValueError("ETF schema: redirect without location")
                target = response.url.join(location)
                if target.scheme != "https":
                    raise ValueError("ETF schema: non-HTTPS redirect")
                url = str(target)
                # Close without reading the intermediate body; cookies have
                # already been added to the shared client by httpx.
                continue
            response.raise_for_status()
            # Avoid a second decompression layer outside the XLSX budgets.
            if response.headers.get("content-encoding", "identity").lower() != "identity":
                raise ValueError("ETF resource limit: encoded HTTP body")
            length = response.headers.get("content-length")
            if length is not None and (not length.isdecimal() or int(length) > MAX_DOWNLOAD_BYTES):
                raise ValueError("ETF resource limit: declared download bytes")
            body = bytearray()
            for chunk in response.iter_bytes(chunk_size=min(64 * 1024, MAX_DOWNLOAD_BYTES + 1)):
                if len(body) + len(chunk) > MAX_DOWNLOAD_BYTES:
                    raise ValueError("ETF resource limit: download bytes")
                body.extend(chunk)
            return bytes(body)
    raise ValueError("ETF resource limit: redirect count")


def _xlsx_rows(data: bytes) -> list[list[str]]:
    """Read only bounded ZIP members; cap XML rows before retaining them."""
    import zipfile

    from defusedxml import ElementTree as DET

    if len(data) > MAX_DOWNLOAD_BYTES:
        raise ValueError("ETF resource limit: workbook bytes")
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        entries = zf.infolist()
        if len(entries) > MAX_XLSX_ENTRIES:
            raise ValueError("ETF resource limit: ZIP entries")
        if len({entry.filename for entry in entries}) != len(entries):
            raise ValueError("ETF resource limit: duplicate ZIP entries")
        if sum(entry.file_size for entry in entries) > MAX_XLSX_TOTAL_BYTES:
            raise ValueError("ETF resource limit: ZIP total bytes")
        for entry in entries:
            if entry.file_size > MAX_XLSX_MEMBER_BYTES:
                raise ValueError("ETF resource limit: ZIP member bytes")
            if entry.file_size > max(entry.compress_size, 1) * MAX_XLSX_COMPRESSION_RATIO:
                raise ValueError("ETF resource limit: ZIP compression ratio")

        def read_member(name: str) -> bytes:
            with zf.open(name) as member:
                content = member.read(MAX_XLSX_MEMBER_BYTES + 1)
            if len(content) > MAX_XLSX_MEMBER_BYTES:
                raise ValueError("ETF resource limit: actual member bytes")
            return content

        shared = [
            "".join(t.text or "" for t in si.iter(f"{_XLSX_NS}t"))
            for si in DET.fromstring(read_member("xl/sharedStrings.xml")).iter(f"{_XLSX_NS}si")
        ]
        sheet = read_member("xl/worksheets/sheet1.xml")
    rows: list[list[str]] = []
    for _, row in DET.iterparse(io.BytesIO(sheet), events=("end",)):
        if row.tag != f"{_XLSX_NS}row":
            continue
        if len(rows) >= MAX_XLSX_ROWS:
            raise ValueError("ETF resource limit: worksheet rows")
        cells = [""] * len(_JEDI_COLUMNS)
        seen_columns: set[int] = set()
        for cell in row.findall(f"{_XLSX_NS}c"):
            ref = _CELL_REF.fullmatch(cell.get("r", ""))
            if not ref or ref.group(2) != row.get("r") or len(ref.group(1)) != 1:
                raise ValueError("ETF schema: invalid cell reference")
            column = ord(ref.group(1)) - ord("A")
            if column >= len(cells) or column in seen_columns:
                raise ValueError("ETF schema: unexpected or duplicate column")
            seen_columns.add(column)
            v = cell.find(f"{_XLSX_NS}v")
            raw = v.text if v is not None and v.text is not None else ""
            if cell.get("t") == "s" and raw:
                if not raw.isdecimal() or int(raw) >= len(shared):
                    raise ValueError("ETF schema: invalid shared string index")
                raw = shared[int(raw)]
            elif cell.get("t") == "inlineStr":
                raw = "".join(t.text or "" for t in cell.iter(f"{_XLSX_NS}t"))
            cells[column] = raw
        rows.append(cells)
        row.clear()
    return rows


def parse_vaneck(data: bytes) -> tuple[date | None, list[tuple[str, Decimal]]]:
    """Excel «All Holdings» de VanEck. Solo cotizadas en EEUU (ticker «XXXX US» e
    ISIN US...): excluye cotizadas extranjeras («MRO LN», «9412 JP») y las que
    cotizan en EEUU con ISIN foraneo, cuya correspondencia con el ticker de la
    app no esta verificada. Fecha de corte de la cabecera."""
    rows = _xlsx_rows(data)
    head = _JEDI_DATE.search(rows[0][0]) if rows and rows[0] else None
    if head is None:
        raise ValueError("ETF invalid equity date")
    try:
        as_of = datetime.strptime(head.group(1), "%m/%d/%Y").date()
    except ValueError as exc:
        raise ValueError("ETF invalid equity date") from exc
    # Fail closed on provider schema changes rather than relabeling columns.
    if len(rows) < 3 or [c.strip() for c in rows[2]] != _JEDI_COLUMNS:
        raise ValueError("ETF schema: unexpected holdings columns")
    out: list[tuple[str, Decimal]] = []
    for cells in rows[3:]:
        match = _JEDI_TICKER.match(cells[2].strip().upper())
        if not match:
            continue
        isin = cells[3].strip()
        if not _ISIN.fullmatch(isin):
            raise ValueError("ETF schema: invalid ISIN")
        if not isin.startswith("US"):
            continue
        weight = _pct(cells[6], fraction=False)
        if weight is None:
            raise ValueError("ETF invalid equity weight")
        out.append((match.group(1), weight))
    return as_of, out


_PARSERS = {"UFO": parse_procure, "NASA": parse_tema, "JEDI": parse_vaneck}


def refresh_etf_holdings(db: Session | None = None, client: httpx.Client | None = None) -> dict:
    """Recarga cada ETF; devuelve el estado por ETF. Nunca lanza."""
    from app.core.database import SessionLocal

    own_db = db is None
    session = db or SessionLocal()
    http = client or httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
    out: dict[str, str] = {}
    try:
        for etf, src in SOURCES.items():
            try:
                if src.direct_url:
                    links = [src.direct_url]
                else:
                    page = _download_bytes(http, src.page).decode("utf-8-sig")
                    links = sorted(set(re.findall(src.link_re, page)))
                if not links:
                    out[etf] = "sin enlace de holdings"
                    continue
                best: tuple[date, str, list[tuple[str, Decimal]]] | None = None
                for link in links:
                    try:  # un enlace roto (404 de un mes anterior) no aborta los demas
                        payload = _download_bytes(http, link)
                        as_of, rows = _PARSERS[etf](payload if src.binary else payload.decode("utf-8-sig"))
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("etf_holdings %s enlace %s fallo: %s", etf, link, exc)
                        continue
                    if as_of and as_of <= date.today() and len({ticker for ticker, _ in rows}) >= MIN_ROWS and (best is None or as_of > best[0]):
                        best = (as_of, link, rows)
                if best is None:
                    out[etf] = "ningun fichero valido: se conserva la carga anterior (si la hay)"
                    continue
                as_of, link, rows = best
                if sum(w for _, w in rows) > Decimal("105"):
                    out[etf] = "pesos incoherentes: se conserva la carga anterior"
                    continue
                weights: dict[str, Decimal] = {}
                conflicting = False
                for ticker, weight in rows:
                    if ticker in weights and weights[ticker] != weight:
                        conflicting = True
                        break
                    weights[ticker] = weight
                if conflicting:
                    out[etf] = "pesos duplicados contradictorios: se conserva la carga anterior"
                    continue
                stored_as_of = session.scalar(
                    select(func.max(EtfHolding.as_of)).where(EtfHolding.etf == etf)
                )
                if stored_as_of is not None and as_of < stored_as_of:
                    out[etf] = "fichero anterior al guardado: se conserva la carga anterior"
                    continue
                session.execute(delete(EtfHolding).where(EtfHolding.etf == etf))
                seen: set[str] = set()
                for ticker, weight in rows:
                    if ticker in seen:
                        continue
                    seen.add(ticker)
                    session.add(EtfHolding(etf=etf, ticker=ticker, weight_pct=weight, as_of=as_of, source_url=link))
                session.commit()
                out[etf] = f"ok {len(seen)} holdings as_of {as_of.isoformat()}"
            except Exception as exc:  # noqa: BLE001 - un emisor caido no afecta al otro
                session.rollback()
                logger.warning("etf_holdings %s fallo: %s", etf, exc)
                out[etf] = f"error {type(exc).__name__}: se conserva la carga anterior"
    finally:
        if client is None:
            http.close()
        if own_db:
            session.close()
    return out


def etfs_for_tickers(db: Session, tickers: set[str], today: date | None = None) -> dict[str, list[dict]]:
    """ticker -> ETFs que lo tienen con peso >= 2 % y holdings de <= 45 dias."""
    if not tickers:
        return {}
    today = today or date.today()
    cutoff = today - timedelta(days=MAX_AGE_DAYS)
    rows = db.scalars(
        select(EtfHolding)
        .where(
            EtfHolding.ticker.in_({t.upper() for t in tickers}),
            EtfHolding.weight_pct >= MIN_WEIGHT_PCT,
            EtfHolding.as_of >= cutoff,
            EtfHolding.as_of <= today,
        )
        .order_by(EtfHolding.weight_pct.desc())
    ).all()
    out: dict[str, list[dict]] = {}
    for row in rows:
        src = SOURCES.get(row.etf)
        out.setdefault(row.ticker, []).append(
            {
                "ticker": row.etf,
                "name": src.name if src else row.etf,
                "kind": "etf",
                "weight_pct": round(float(row.weight_pct), 2),
                "holdings_as_of": row.as_of.isoformat(),
                "source_url": row.source_url,
            }
        )
    return out
