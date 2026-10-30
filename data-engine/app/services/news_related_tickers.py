"""Tickers relacionados de una noticia, con cierre y variacion del dia.

Solo evidencia explicita en el texto (titular + resumen guardados): cashtag
($TKR), «(NYSE: TKR)» o el nombre completo y distintivo de una empresa que
ya conocemos. Una sigla suelta no basta, un nombre ambiguo (dos empresas, o
una palabra corriente como «Orange») no se vincula. Las cotizaciones salen
de market_prices (cierres oficiales datados) con la misma regla de sesion
comun que Movers/Watchlist: la variacion solo se publica si son dos cierres
consecutivos; si no, None. Nunca se inventa un precio ni se mezcla un cierre
con una cotizacion en vivo. Sin llamadas de red ni LLM: coste = 2 lecturas
SQL por peticion de feed."""

from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Company, MarketPrice
from app.services.etf_holdings import etfs_for_tickers
from app.services.market_change import OFFICIAL_CLOSE_SOURCES, common_sessions
from app.services.price_units import listing_price

MAX_RELATED = 6
INDEX_TTL_SECONDS = 600

# Una empresa de nombre de UNA palabra («Progressive», «Southern») solo se
# vincula si en el texto le sigue un sufijo legal («Progressive Corp»): sola es
# una palabra corriente («Progressive policies», «Southern Europe»).
_LEGAL_ADJ = {
    "inc", "corp", "corporation", "company", "ltd", "plc", "llc", "limited", "nv", "sa", "ag",
    "group", "holdings", "holding",
}

# Alias de UNA palabra verificados a mano: marcas sin otro significado corriente.
# Solo cuentan si ese ticker existe en companies.
VERIFIED_ALIASES = {
    "telefonica": "TEF", "nvidia": "NVDA", "microsoft": "MSFT", "broadcom": "AVGO",
    "qualcomm": "QCOM", "palantir": "PLTR", "iberdrola": "IBE", "inditex": "ITX",
}


@dataclass(frozen=True)
class CompanyRef:
    id: int
    ticker: str | None
    name: str | None
    currency: str | None

_SUFFIX = {
    "inc", "corp", "corporation", "co", "company", "ltd", "plc", "sa", "nv", "ag", "se",
    "the", "group", "holdings", "holding", "limited", "llc", "lp", "spa", "oyj", "ab", "as",
}
_CASHTAG = re.compile(r"\$([A-Za-z]{1,6}(?:\.[A-Za-z]{1,2})?)\b")
_EXCHANGE = re.compile(
    r"\b(?:NYSE|NASDAQ|AMEX|BME|LSE|EPA|ETR)\s*:\s*([A-Za-z]{1,6}(?:\.[A-Za-z]{1,2})?)\b",
    re.IGNORECASE,
)
_WORD = re.compile(r"[a-z0-9&']+")


def _fold(text: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(ch)
    )


def _name_key(name: str | None) -> str | None:
    """Nombre sin sufijos legales, en minusculas y sin acentos; None si es
    demasiado corto/generico para vincular (una palabra de menos de 7
    letras: «Orange», «Apple»... puede ser una palabra corriente)."""
    words = [w for w in _WORD.findall(_fold(re.sub(r"[.,]", "", name or ""))) if w not in _SUFFIX]
    if not words:
        return None
    key = " ".join(words)
    if len(words) == 1 and len(key) < 7:
        return None
    return key if len(key) >= 7 else None


def build_index(companies: list[CompanyRef | Company]) -> tuple[dict[str, CompanyRef | Company], dict[str, CompanyRef | Company]]:
    """(nombre -> empresa, ticker -> empresa). Un nombre compartido por dos
    empresas se descarta: ambiguo."""
    by_name: dict[str, CompanyRef | Company | None] = {}
    by_ticker: dict[str, CompanyRef | Company] = {}
    for company in companies:
        if company.ticker:
            by_ticker.setdefault(company.ticker.upper(), company)
        key = _name_key(company.name)
        if key is None:
            continue
        if key in by_name and by_name[key] is not None and by_name[key].id != company.id:
            by_name[key] = None
        else:
            by_name.setdefault(key, company)
    for alias, tkr in VERIFIED_ALIASES.items():
        if tkr in by_ticker and by_name.get(alias, "x") is not None:
            by_name[alias] = by_ticker[tkr]
    return {k: v for k, v in by_name.items() if v is not None}, by_ticker


def mentioned_companies(
    text: str,
    by_name: dict[str, CompanyRef | Company],
    by_ticker: dict[str, CompanyRef | Company],
) -> list[CompanyRef | Company]:
    found: dict[int, Company] = {}
    for pattern in (_CASHTAG, _EXCHANGE):
        for match in pattern.finditer(text or ""):
            company = by_ticker.get(match.group(1).upper())
            if company is not None:
                found.setdefault(company.id, company)
    words = _WORD.findall(_fold(text or ""))
    max_n = 4
    for size in range(1, max_n + 1):
        for i in range(len(words) - size + 1):
            company = by_name.get(" ".join(words[i : i + size]))
            if company is not None and size == 1 and words[i] not in VERIFIED_ALIASES:
                nxt = words[i + 1] if i + 1 < len(words) else None
                if nxt not in _LEGAL_ADJ:
                    company = None
            if company is not None:
                found.setdefault(company.id, company)
    return list(found.values())


def quotes_for(db: Session, company_ids: set[int]) -> dict[int, dict]:
    """Ultimo cierre oficial por empresa y su variacion (solo sesion comun)."""
    if not company_ids:
        return {}
    session_day, prev_session_day = common_sessions(db)
    if session_day is None:
        return {}
    since: date = session_day - timedelta(days=14)
    rows = db.execute(
        select(
            MarketPrice.company_id,
            MarketPrice.date,
            MarketPrice.close,
            MarketPrice.adj_close,
            MarketPrice.quote_currency,
        )
        .where(
            MarketPrice.company_id.in_(company_ids),
            MarketPrice.source.in_(OFFICIAL_CLOSE_SOURCES),
            MarketPrice.date >= since,
        )
        .order_by(MarketPrice.company_id, MarketPrice.date.desc())
    ).all()
    latest: dict[int, tuple] = {}
    previous: dict[int, tuple] = {}
    for company_id, day, close, adj_close, unit in rows:
        if close is None:
            continue
        if company_id not in latest:
            latest[company_id] = (day, close, adj_close, unit)
        elif company_id not in previous:
            previous[company_id] = (day, close, adj_close, unit)
    companies = {
        c.id: c for c in db.scalars(select(Company).where(Company.id.in_(list(latest)))).all()
    } if latest else {}
    out: dict[int, dict] = {}
    for company_id, (day, close, adj_close, unit) in latest.items():
        company = companies.get(company_id)
        # Precio en la divisa principal de SU cotizacion (TSCO.L: 255 GBp se
        # publica como 2,55 GBP), igual que el mercado del dia (market_change).
        listed = _listed(close, unit, company)
        prev = previous.get(company_id)
        change_pct = None
        if (
            listed is not None
            and day == session_day
            and prev is not None
            and prev_session_day is not None
            and prev[0] == prev_session_day
        ):
            change_pct = _session_change(company, (close, adj_close, unit), prev[1:])
        out[company_id] = {
            "price": float(listed[0]) if listed is not None else None,
            "date": day.isoformat(),
            "change_pct": change_pct,
            **({"currency": listed[1]} if listed is not None else {}),
        }
    return out


def _listed(value, unit, company) -> tuple[Decimal, str | None] | None:
    if value is None:
        return None
    amount = Decimal(str(value))
    if company is None or not unit:
        # Fila legacy sin unidad declarada: el cierre tal cual (como antes).
        return amount, getattr(company, "currency", None)
    return listing_price(amount, quote_currency=unit, company=company)


def _session_change(company, latest: tuple, previous: tuple) -> float | None:
    """Variacion entre dos sesiones en una sola unidad.

    Cierres ajustados si ambas filas los traen (un split 4:1 entre las dos
    sesiones no es un -75 %), como las alertas y el digest de cartera. Cada
    cierre en la divisa principal de su cotizacion: 250 GBp y 2,55 GBP son
    +2 %, no -99 %. Divisas distintas: sin variacion.
    """
    (close, adj, unit), (p_close, p_adj, p_unit) = latest, previous
    if adj is not None and p_adj is not None and adj > 0 and p_adj > 0:
        close, p_close = adj, p_adj
    if unit == p_unit or not unit or not p_unit:
        last, prev = Decimal(str(close)), Decimal(str(p_close))
    else:
        a = _listed(close, unit, company)
        b = _listed(p_close, p_unit, company)
        if a is None or b is None or a[1] != b[1]:
            return None
        last, prev = a[0], b[0]
    if not prev:
        return None
    return round(float((last - prev) / prev * 100), 2)


_INDEX_CACHE: dict = {"at": 0.0, "value": None}


def _cached_index(db: Session):
    """Indice en memoria con TTL: evita leer toda la tabla companies en cada
    peticion del feed. Solo 4 columnas."""
    now = time.monotonic()
    if _INDEX_CACHE["value"] is None or now - _INDEX_CACHE["at"] > INDEX_TTL_SECONDS:
        rows = db.execute(select(Company.id, Company.ticker, Company.name, Company.currency)).all()
        refs = [CompanyRef(r[0], r[1], r[2], r[3]) for r in rows]
        _INDEX_CACHE["value"] = build_index(refs)
        _INDEX_CACHE["at"] = now
    return _INDEX_CACHE["value"]


def related_for_events(
    db: Session,
    items: list[tuple[int, Company | None, str]],
) -> dict[int, list[dict]]:
    """items = (event_id, empresa_principal, texto). Devuelve event_id ->
    lista [principal, *relacionadas] con cierre/variacion; vacio si no hay
    ninguna relacionada distinta de la principal (la tira seria redundante)."""
    by_name, by_ticker = _cached_index(db)
    try:
        etf_by_ticker = etfs_for_tickers(
            db, {p.ticker for _, p, _ in items if p is not None and p.ticker}
        )
    except Exception:  # noqa: BLE001 - complemento: sin ETFs, la tira sigue
        etf_by_ticker = {}
    per_event: dict[int, list[Company]] = {}
    ids: set[int] = set()
    for event_id, primary, text in items:
        others = [
            c
            for c in mentioned_companies(text, by_name, by_ticker)
            if primary is None or c.id != primary.id
        ][:MAX_RELATED]
        if not others and not (primary is not None and primary.ticker in etf_by_ticker):
            continue
        chain = ([primary] if primary is not None else []) + others
        per_event[event_id] = chain
        ids.update(c.id for c in chain)
    quotes = quotes_for(db, ids)
    primary_ids = {event_id: (primary.id if primary is not None else None) for event_id, primary, _ in items}
    result: dict[int, list[dict]] = {}
    for event_id, chain in per_event.items():
        result[event_id] = [
            {
                "ticker": c.ticker,
                "name": c.name,
                "currency": c.currency,
                "primary": c.id == primary_ids.get(event_id),
                **(quotes.get(c.id) or {"price": None, "date": None, "change_pct": None}),
            }
            for c in chain
        ]
        primary_ticker = next((c.ticker for c in chain if c.id == primary_ids.get(event_id)), None)
        if primary_ticker is not None:
            result[event_id].extend(etf_by_ticker.get(primary_ticker, []))
    return result
