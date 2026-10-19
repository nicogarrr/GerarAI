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
import unicodedata
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Company, MarketPrice
from app.services.market_change import OFFICIAL_CLOSE_SOURCES, common_sessions

MAX_RELATED = 6

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


def build_index(companies: list[Company]) -> tuple[dict[str, Company], dict[str, Company]]:
    """(nombre -> empresa, ticker -> empresa). Un nombre compartido por dos
    empresas se descarta: ambiguo."""
    by_name: dict[str, Company | None] = {}
    by_ticker: dict[str, Company] = {}
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
    return {k: v for k, v in by_name.items() if v is not None}, by_ticker


def mentioned_companies(
    text: str,
    by_name: dict[str, Company],
    by_ticker: dict[str, Company],
) -> list[Company]:
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
        select(MarketPrice.company_id, MarketPrice.date, MarketPrice.close)
        .where(
            MarketPrice.company_id.in_(company_ids),
            MarketPrice.source.in_(OFFICIAL_CLOSE_SOURCES),
            MarketPrice.date >= since,
        )
        .order_by(MarketPrice.company_id, MarketPrice.date.desc())
    ).all()
    latest: dict[int, tuple] = {}
    previous: dict[int, tuple] = {}
    for company_id, day, close in rows:
        if close is None:
            continue
        if company_id not in latest:
            latest[company_id] = (day, float(close))
        elif company_id not in previous:
            previous[company_id] = (day, float(close))
    out: dict[int, dict] = {}
    for company_id, (day, close) in latest.items():
        prev = previous.get(company_id)
        comparable = (
            day == session_day
            and prev is not None
            and prev_session_day is not None
            and prev[0] == prev_session_day
            and prev[1]
        )
        out[company_id] = {
            "price": close,
            "date": day.isoformat(),
            "change_pct": round((close - prev[1]) / prev[1] * 100, 2) if comparable else None,
        }
    return out


def related_for_events(
    db: Session,
    items: list[tuple[int, Company | None, str]],
) -> dict[int, list[dict]]:
    """items = (event_id, empresa_principal, texto). Devuelve event_id ->
    lista [principal, *relacionadas] con cierre/variacion; vacio si no hay
    ninguna relacionada distinta de la principal (la tira seria redundante)."""
    companies = list(db.scalars(select(Company)).all())
    by_name, by_ticker = build_index(companies)
    per_event: dict[int, list[Company]] = {}
    ids: set[int] = set()
    for event_id, primary, text in items:
        others = [
            c
            for c in mentioned_companies(text, by_name, by_ticker)
            if primary is None or c.id != primary.id
        ][:MAX_RELATED]
        if not others:
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
    return result
