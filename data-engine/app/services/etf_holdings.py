"""Holdings oficiales de ETFs tematicos (UFO, NASA) para la tira de noticias.

Fuente: el CSV publicado por el propio emisor (Procure, Tema), descubierto en
la pagina del fondo (la URL lleva la fecha). Solo se guardan tickers de renta
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
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.entities import EtfHolding

logger = logging.getLogger(__name__)

MIN_WEIGHT_PCT = Decimal("2")  # peso minimo para vincular una noticia a un ETF
MAX_AGE_DAYS = 45
MIN_ROWS = 10
_TICKER = re.compile(r"^[A-Z]{1,5}$")


@dataclass(frozen=True)
class EtfSource:
    etf: str
    name: str
    page: str
    link_re: str


SOURCES = {
    "UFO": EtfSource("UFO", "Procure Space ETF", "https://procureetfs.com/ufo/",
                     r"https://procureetfs\.com/[^\"' ]*UFO[^\"' ]*Holdings[^\"' ]*\.csv"),
    "NASA": EtfSource("NASA", "Tema Space Innovators ETF", "https://temaetfs.com/nasa",
                      r"https://temaetfs\.com/[^\"' ]*NASA-holdings-\d+\.csv"),
}


def _pct(raw: str | None, *, fraction: bool) -> Decimal | None:
    try:
        value = Decimal((raw or "").strip().rstrip("%").replace(",", ""))
    except InvalidOperation:
        return None
    return value * 100 if fraction else value


def parse_procure(text: str) -> tuple[date | None, list[tuple[str, Decimal]]]:
    rows: list[tuple[str, Decimal]] = []
    as_of: date | None = None
    for rec in csv.DictReader(io.StringIO(text.lstrip("\ufeff"))):
        ticker = (rec.get("StockTicker") or "").strip().upper()
        weight = _pct(rec.get("Weightings"), fraction=False)
        try:
            day = datetime.strptime((rec.get("Date") or "").strip(), "%m/%d/%Y").date()
        except ValueError:
            continue
        if not _TICKER.match(ticker) or weight is None:
            continue
        as_of = max(as_of, day) if as_of else day
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
        if not _TICKER.match(ticker) or not (rec.get("cusip") or "").strip() or weight is None:
            continue
        if (rec.get("country") or "").strip() != "United States":
            continue
        try:
            day = datetime.strptime((rec.get("holdings_date") or "").strip(), "%Y-%m-%d").date()
        except ValueError:
            continue
        as_of = max(as_of, day) if as_of else day
        rows.append((ticker, weight))
    return as_of, rows


_PARSERS = {"UFO": parse_procure, "NASA": parse_tema}


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
                page = http.get(src.page)
                page.raise_for_status()
                links = sorted(set(re.findall(src.link_re, page.text)))
                if not links:
                    out[etf] = "sin enlace de holdings"
                    continue
                best: tuple[date, str, list[tuple[str, Decimal]]] | None = None
                for link in links:
                    try:  # un enlace roto (404 de un mes anterior) no aborta los demas
                        resp = http.get(link)
                        resp.raise_for_status()
                        as_of, rows = _PARSERS[etf](resp.text)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("etf_holdings %s enlace %s fallo: %s", etf, link, exc)
                        continue
                    if as_of and len(rows) >= MIN_ROWS and (best is None or as_of > best[0]):
                        best = (as_of, link, rows)
                if best is None:
                    out[etf] = "ningun fichero valido: se conserva la carga anterior (si la hay)"
                    continue
                as_of, link, rows = best
                if sum(w for _, w in rows) > Decimal("105"):
                    out[etf] = "pesos incoherentes: se conserva la carga anterior"
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
    cutoff = (today or date.today()) - timedelta(days=MAX_AGE_DAYS)
    rows = db.scalars(
        select(EtfHolding)
        .where(
            EtfHolding.ticker.in_({t.upper() for t in tickers}),
            EtfHolding.weight_pct >= MIN_WEIGHT_PCT,
            EtfHolding.as_of >= cutoff,
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
