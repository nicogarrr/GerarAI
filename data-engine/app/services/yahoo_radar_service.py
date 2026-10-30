"""Radar global de candidatos deep value via Yahoo Finance (fuente NO oficial).

Solo PROPONE candidatos: nada de lo que devuelve se persiste como hecho
financiero ni se sirve como dato verificado. Cada cifra lleva la etiqueta de
fuente no oficial y el rotulo de la respuesta dice que el cotejo oficial es
previo a cualquier uso (para HKEX, la pagina de busqueda de HKEXnews).

Por que existe: los conectores oficiales (SEC/otros) no cubren Asia, asi que
el universo propio no descubre valores como una inmobiliaria de HK a 0,2x
libros con dividendo alto. Yahoo si tiene cobertura global, pero es fuente no
oficial: el radar lo deja explicito en cada candidato.

El fetcher es inyectable para tests sin red (fixtures grabados). El parseo es
fail-closed: falta un campo -> None (N/D), nunca 0 ni inventado.

Verificado contra el Yahoo real el 28-oct-2026 (sondas minimas, sandbox):
- El operador ``in`` no existe: 400 "Unsupported operator: in". Regiones se
  filtran con ``or`` de ``eq`` (lista de soportados: or, eq, gt, lt, ...).
- NO existe filtro P/B: ``pricebookratio`` (y variantes) se IGNORA EN
  SILENCIO (mismo total). Por eso el P/B se filtra en cliente tras el parseo:
  un operando ignorado serviria resultados sin filtrar como si lo estuvieran.
- ``dividendyield`` SI filtra, en PORCENTAJE (5 = 5%).
- Claves reales del quote: ``priceToBook`` (ratio), ``dividendYield`` (%,
  a veces 0 en HK pese a pasar el filtro) y ``trailingAnnualDividendYield``
  (fraccion). Yield ambiguo o 0 -> N/D, nunca 0,0%.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from time import monotonic
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company
from app.valuation.currency import normalize_currency

YAHOO_SCREENER_URL = "https://query1.finance.yahoo.com/v1/finance/screener"
YAHOO_LABEL = "Yahoo Finance (fuente no oficial)"
# Pagina oficial de busqueda de anuncios de HKEX, via de cotejo para valores HK.
HKEXNEWS_SEARCH_URL = "https://www1.hkexnews.hk/search/titlesearch.xhtml"
RADAR_LABEL = (
    "Radar global Yahoo (fuente no oficial). SOLO propone candidatos: las "
    "cifras no son dato verificado hasta el cotejo con la fuente oficial de "
    "cada mercado (para HKEX, HKEXnews). Nada de aqui se guarda como hecho "
    "financiero."
)
DEFAULT_REGIONS = ("us", "es", "de", "fr", "gb", "it", "nl", "se", "ch", "hk", "jp", "ca", "au")
EXTREME_YIELD = Decimal("0.25")  # >25% TTM: posible dividendo especial o error de fuente
MAX_SIZE = 100


@dataclass
class RadarCandidate:
    symbol: str
    name: str | None
    exchange: str | None
    currency: str | None
    price_to_book: Decimal | None
    dividend_yield: Decimal | None
    yield_extremo_revisar: bool
    fuente: str = YAHOO_LABEL
    en_universo_propio: bool = False
    via_cotejo: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def build_screener_query(
    *,
    yield_min: Decimal,
    regions: list[str],
    size: int,
) -> dict[str, Any]:
    """Cuerpo del POST al screener no oficial de Yahoo. Funcion pura.

    Solo operadores y campos verificados (ver docstring del modulo): el P/B
    NO se pone en la query porque Yahoo lo ignora en silencio; se filtra en
    cliente. ``dividendyield`` va en porcentaje (0.05 -> 5%)."""
    region_ops = [
        {"operator": "eq", "operands": ["region", r.lower()]} for r in regions
    ]
    operands: list[dict[str, Any]] = [
        region_ops[0] if len(region_ops) == 1 else {"operator": "or", "operands": region_ops}
    ]
    if yield_min > 0:
        operands.append({"operator": "gt", "operands": ["dividendyield", float(yield_min * 100)]})
    return {
        "offset": 0,
        "size": max(1, min(size, MAX_SIZE)),
        "sortField": "intradaymarketcap",
        "sortType": "desc",
        "quoteType": "EQUITY",
        "query": {"operator": "and", "operands": operands},
        "userId": "",
        "userIdType": "guid",
    }


def _raw_number(node: Any) -> Decimal | None:
    """Yahoo devuelve numeros como {raw, fmt} o planos; ausente -> None."""
    if isinstance(node, dict):
        node = node.get("raw")
    if node is None:
        return None
    try:
        value = Decimal(str(node))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not value.is_finite() or value < 0:
        return None
    return value


def _first_number(quote: dict[str, Any], keys: tuple[str, ...]) -> Decimal | None:
    for key in keys:
        value = _raw_number(quote.get(key))
        if value is not None:
            return value
    return None


def parse_screener_quotes(payload: dict[str, Any]) -> list[RadarCandidate]:
    """Respuesta cruda del screener -> candidatos. Fail-closed por fila."""
    finance = payload.get("finance") if isinstance(payload, dict) else None
    result = (finance or {}).get("result") or []
    quotes = result[0].get("quotes") if result else []
    if not isinstance(quotes, list):
        return []
    out: list[RadarCandidate] = []
    for quote in quotes:
        if not isinstance(quote, dict):
            continue
        symbol = str(quote.get("symbol") or "").strip().upper()
        if not symbol:
            continue  # sin identidad no hay candidato
        # Unidades por campo (verificado 28-oct): "trailingAnnualDividendYield"
        # es fraccion (0.081 = 8,1%) y "dividendYield" es porcentaje (8.1). El
        # 0 es ambiguo en Yahoo (valor real o ausencia: en HK devuelve 0 aun
        # pasando el filtro de yield), asi que 0/ausente -> N/D, nunca 0,0%.
        #
        # Manda "dividendYield": es el campo que filtra el propio screener y
        # sale bien en todas las divisas. "trailingAnnualDividendYield" divide
        # el dividendo en la divisa principal entre un precio en subunidad
        # (verificado 30-oct: TSCO.L 538 GBp, dividendo 0.148 GBP ->
        # 0.000279 = 0,03 % en vez de 2,78 %; SHEL.L 0,04 % en vez de 2,9 %).
        # Solo se usa como respaldo si la cotizacion NO va en subunidad.
        exchange = quote.get("fullExchangeName") or quote.get("exchange")
        currency = quote.get("currency")
        pct = _raw_number(quote.get("dividendYield"))
        yld = (pct / Decimal(100)) if pct is not None and pct > 0 else None
        if yld is None and normalize_currency(str(currency or ""))[1] == 1:
            trailing = _raw_number(quote.get("trailingAnnualDividendYield"))
            yld = trailing if trailing is not None and trailing > 0 else None
        # P/B: Yahoo divide el precio (divisa del listado, ya en principal)
        # entre el valor contable en la divisa de REPORTE sin convertir
        # (verificado 30-oct: HSBA.L 12,872 GBP / 7,554 USD = 1,70 en vez de
        # ~2,28). Divisas distintas -> N/D (y no pasa el filtro P/B).
        price_to_book = _first_number(quote, ("priceToBook",))
        financial = normalize_currency(str(quote.get("financialCurrency") or ""))[0]
        listing = normalize_currency(str(currency or ""))[0]
        if financial and listing and financial != listing:
            price_to_book = None
        out.append(
            RadarCandidate(
                symbol=symbol,
                name=quote.get("longName") or quote.get("shortName"),
                exchange=str(exchange) if exchange else None,
                currency=str(currency) if currency else None,
                price_to_book=price_to_book,
                dividend_yield=yld,
                yield_extremo_revisar=bool(yld is not None and yld > EXTREME_YIELD),
            )
        )
    return out


def _via_cotejo(candidate: RadarCandidate) -> str | None:
    hay = f"{candidate.exchange or ''} {candidate.currency or ''}".upper()
    if "HKEX" in hay or "HONG KONG" in hay or candidate.currency == "HKD":
        return HKEXNEWS_SEARCH_URL
    return None


# Cache corta del screener: cada vista del radar repetia la sesion crumb de
# Yahoo (2 peticiones) y el POST del screener. Datos publicos de Yahoo, iguales
# para todos (el marcado contra el universo propio se hace despues, por
# peticion). Un fallo no se cachea. La respuesta lleva ``_fetched_at`` para
# que "generado en" diga cuando se consulto Yahoo de verdad.
_SCREENER_TTL_S = 600.0
_SCREENER_MAX_ENTRIES = 32
_screener_lock = threading.Lock()
_screener_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def fetch_screener(query: dict[str, Any]) -> dict[str, Any]:
    """Screener de Yahoo con cache de 10 min por query (red, solo runtime)."""
    key = json.dumps(query, sort_keys=True, default=str)
    now = monotonic()
    with _screener_lock:
        hit = _screener_cache.get(key)
        if hit is not None and now - hit[0] < _SCREENER_TTL_S:
            return hit[1]
    payload = {**_post_screener(query), "_fetched_at": datetime.now(UTC).isoformat(timespec="seconds")}
    with _screener_lock:
        for stale in [k for k, (ts, _) in _screener_cache.items() if now - ts >= _SCREENER_TTL_S]:
            _screener_cache.pop(stale, None)
        if len(_screener_cache) >= _SCREENER_MAX_ENTRIES:
            _screener_cache.pop(min(_screener_cache, key=lambda k: _screener_cache[k][0]), None)
        _screener_cache[key] = (monotonic(), payload)
    return payload


def _post_screener(query: dict[str, Any]) -> dict[str, Any]:
    """POST real al screener de Yahoo con sesion crumb."""

    from app.services.connectors.ca_insider_yahoo import yahoo_session

    client, crumb = yahoo_session()
    try:
        response = client.post(
            YAHOO_SCREENER_URL,
            params={"crumb": crumb, "formatted": "false", "lang": "en-US", "region": "US"},
            json=query,
            timeout=20,
        )
        response.raise_for_status()
        return response.json()
    finally:
        client.close()


def run_radar(
    db: Session,
    *,
    fetcher: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    pb_max: Decimal | None = Decimal("1.0"),
    yield_min: Decimal = Decimal("0"),
    regions: list[str] | None = None,
    size: int = 50,
) -> tuple[list[RadarCandidate], str, list[str]]:
    """Ejecuta el radar y marca que candidatos ya estan en el universo propio.

    No escribe nada en la base de datos: los candidatos son propuestas, no
    hechos. Devuelve (candidatos, generado_en ISO UTC, regiones usadas).
    """
    # Resolucion en tiempo de llamada (no en el default) para que los tests
    # puedan sustituir fetch_screener sin red.
    fetcher = fetcher or fetch_screener
    regs = regions or list(DEFAULT_REGIONS)
    payload = fetcher(build_screener_query(yield_min=yield_min, regions=regs, size=size))
    candidates = parse_screener_quotes(payload)
    if pb_max is not None:
        # El P/B se filtra aqui: Yahoo ignora el campo en la query (verificado
        # 28-oct). Sin cifra de P/B no se puede afirmar que pasa el filtro:
        # fail-closed, fuera.
        candidates = [
            c for c in candidates
            if c.price_to_book is not None and Decimal("0") < c.price_to_book <= pb_max
        ]
    if candidates:
        tickers = {c.symbol for c in candidates}
        # Company no es tenant-scoped (mismo precedente que deep_value_service).
        known = set(
            db.scalars(select(Company.ticker).where(Company.ticker.in_(tickers))).all()
        )
        for candidate in candidates:
            candidate.en_universo_propio = candidate.symbol in known
            candidate.via_cotejo = _via_cotejo(candidate)
    fetched_at = payload.get("_fetched_at") if isinstance(payload, dict) else None
    generado_en = fetched_at if isinstance(fetched_at, str) else datetime.now(UTC).isoformat(timespec="seconds")
    return candidates, generado_en, regs
