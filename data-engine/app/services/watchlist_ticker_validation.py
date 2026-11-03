"""Alta en watchlist: solo empresas que existen en bolsa.

Prod, 3-nov-2026: la watchlist de Nico tenía «GOOGLE» (errata de GOOGL) con su
ficha vacía (bolsa UNKNOWN, sin precios) y cada alta de un símbolo inexistente
encolaba tesis, siembra SEC, DCA y descarga de precios para nada. Aquí se decide
qué ticker guardar, sin crear nada:

1. Ficha del catálogo con identidad real (nombre/bolsa del proveedor o
   precios) vía ``resolve_company`` (exacto, FIGI, clase BRK-B/BRK.B,
   sufijo de mercado): se guarda su ticker canónico (SAN.MC -> SAN).
2. Ficha mínima cuyo ISIN es un listado revisado (``listing_identity``):
   el ticker del listado (BFIT con ISIN de Basic-Fit -> BFIT.AS).
3. Alias del propio catálogo: marca verificada (``ticker_news_lane.
   VERIFIED_ALIASES``: GOOGLE -> GOOGL, FACEBOOK -> META) o nombre de una
   única empresa del catálogo (NETFLIX -> NFLX).
4. Solo en producción, consulta corta a la chart API de Yahoo (la misma que
   usa la app para precios, sin clave): si el símbolo cotiza, vale tal cual;
   si Yahoo dice que no existe, se rechaza salvo alias (paso 3).

Si Yahoo no responde a tiempo (red, CAPTCHA, rate limit) y no hay alias, el
alta sigue como antes («sin verificar»): una caída del proveedor no debe
bloquear la watchlist. Fuera de producción no hay llamada de red (tests y
local herméticos) y lo desconocido también queda «sin verificar».
"""

from __future__ import annotations

import difflib
import logging
import re
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.models import Company, MarketPrice

logger = logging.getLogger(__name__)

# Plazo total de la consulta a Yahoo: el alta es interactiva.
PROBE_TIMEOUT_SECONDS = 3.0
_NAME_TOKEN = re.compile(r"[A-Z0-9]+")

Status = Literal["known", "unknown", "unverified"]


@dataclass(frozen=True)
class WatchSymbolVerdict:
    """Qué ticker guardar y por qué.

    ``known``: existe (``ticker`` es el canónico). ``unknown``: no existe
    (``suggestions`` con candidatos del catálogo). ``unverified``: no se pudo
    comprobar; se guarda el símbolo pedido, como antes.
    """

    status: Status
    ticker: str
    name: str | None = None
    source: str = ""
    suggestions: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ProbeResult:
    """Respuesta de la consulta al proveedor: ``exists`` None = sin respuesta."""

    exists: bool | None
    name: str | None = None


def _network_enabled() -> bool:
    from app.core.config import get_settings

    return get_settings().is_production


def _is_placeholder(company: Company) -> bool:
    from app.services.listing_identity import PLACEHOLDER_EXCHANGES

    name = (company.name or "").strip().upper()
    exchange = (company.exchange or "").strip().upper()
    return (not name or name == (company.ticker or "").strip().upper()) and exchange in PLACEHOLDER_EXCHANGES


def has_real_identity(db: Session, company: Company) -> bool:
    """Ficha con identidad de verdad: no es el stub «ticker sin nombre ni bolsa»,
    o tiene al menos un cierre guardado."""
    if not _is_placeholder(company):
        return True
    return bool(db.scalar(select(exists().where(MarketPrice.company_id == company.id))))


def _real_companies(db: Session):
    from app.services.listing_identity import PLACEHOLDER_EXCHANGES

    return select(Company).where(
        func.upper(func.coalesce(Company.exchange, "")).notin_(sorted(PLACEHOLDER_EXCHANGES))
    )


def _brand_targets(symbol: str) -> list[str]:
    from app.services.ticker_news_lane import VERIFIED_ALIASES

    wanted = "".join(_NAME_TOKEN.findall(symbol))
    out: list[str] = []
    for ticker, brands in VERIFIED_ALIASES.items():
        for brand in brands:
            if "".join(_NAME_TOKEN.findall(brand.upper())) == wanted and ticker not in out:
                out.append(ticker)
    return out


def _name_matches(db: Session, symbol: str) -> list[Company]:
    """Empresas reales del catálogo cuyo nombre empieza por ``symbol`` como palabra
    («NETFLIX» -> «Netflix, Inc.»). Solo símbolos de 5+ letras sin sufijo: los
    cortos son tickers de verdad con más frecuencia que nombres."""
    if len(symbol) < 5 or not symbol.isalpha():
        return []
    rows = db.scalars(
        _real_companies(db).where(func.upper(Company.name).like(f"{symbol}%")).limit(20)
    ).all()
    return [c for c in rows if (_NAME_TOKEN.findall((c.name or "").upper()) or [""])[0] == symbol]


def _alias(db: Session, symbol: str) -> tuple[Company | None, list[str]]:
    """(empresa canónica si el alias es inequívoco, otros candidatos)."""
    from app.services.company_resolver import resolve_company

    for target in _brand_targets(symbol):
        company = resolve_company(db, target)
        if company is not None and has_real_identity(db, company):
            return company, []
    by_name = _name_matches(db, symbol)
    if len(by_name) == 1:
        return by_name[0], []
    return None, [c.ticker for c in by_name[:3]]


def _suggestions(db: Session, symbol: str, seed: list[str]) -> list[str]:
    from app.services.listing_identity import BY_ISIN

    out = list(seed)
    for listing in BY_ISIN.values():
        if listing.ticker.split(".", 1)[0] == symbol.split(".", 1)[0] and listing.ticker not in out:
            out.append(listing.ticker)
    tickers = [t for t in db.scalars(_real_companies(db).with_only_columns(Company.ticker)).all() if t]
    for close in difflib.get_close_matches(symbol, tickers, n=3, cutoff=0.75):
        if close not in out:
            out.append(close)
    return out[:3]


def probe_yahoo(symbol: str, *, timeout: float = PROBE_TIMEOUT_SECONDS) -> ProbeResult:
    """¿Cotiza ``symbol``? Chart API de Yahoo (la de precios de la app), 5 días.

    404/serie vacía = no existe. Red, 429, CAPTCHA o plazo agotado = sin
    respuesta (``exists`` None): el caller no rechaza por un proveedor caído.
    """
    from app.services.connectors.yahoo import chart_listing_probe

    exists_, name = chart_listing_probe(symbol, timeout=timeout)
    if exists_ is None:
        logger.info("watchlist: Yahoo sin respuesta para %s", symbol)
    return ProbeResult(exists=exists_, name=name)


def resolve_watch_symbol(db: Session, raw_symbol: str) -> WatchSymbolVerdict:
    """Ticker a guardar en la watchlist para ``raw_symbol`` (ver docstring del módulo)."""
    from app.services.company_resolver import resolve_company
    from app.services.listing_identity import reviewed_listing

    symbol = raw_symbol.strip().upper()
    company = resolve_company(db, symbol)
    if company is not None and has_real_identity(db, company):
        return WatchSymbolVerdict("known", company.ticker, company.name, "catalogo")
    if company is not None:
        listing = reviewed_listing(company.isin)
        if listing is not None:
            return WatchSymbolVerdict("known", listing.ticker, listing.name, "isin")
    alias, candidates = _alias(db, symbol)

    probe = probe_yahoo(symbol) if _network_enabled() else ProbeResult(exists=None)
    if probe.exists:
        ticker = company.ticker if company is not None else symbol
        return WatchSymbolVerdict("known", ticker, probe.name, "proveedor")
    if alias is not None:
        return WatchSymbolVerdict("known", alias.ticker, alias.name, "alias")
    if probe.exists is False:
        return WatchSymbolVerdict(
            "unknown", symbol, suggestions=_suggestions(db, symbol, candidates)
        )
    return WatchSymbolVerdict("unverified", company.ticker if company is not None else symbol)
