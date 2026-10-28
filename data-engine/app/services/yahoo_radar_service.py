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
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company

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
    pb_max: Decimal | None,
    yield_min: Decimal,
    regions: list[str],
    size: int,
) -> dict[str, Any]:
    """Cuerpo del POST al screener no oficial de Yahoo. Funcion pura."""
    operands: list[dict[str, Any]] = [
        {"operator": "in", "operands": ["region", [r.lower() for r in regions]]}
    ]
    if pb_max is not None:
        operands.append({"operator": "lt", "operands": ["pricebookratio", float(pb_max)]})
    if yield_min > 0:
        operands.append({"operator": "gt", "operands": ["dividendyield", float(yield_min)]})
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
        # Unidades por campo (no se mezclan): "dividendYield" del screener
        # viene en porcentaje (8.1 = 8,1%); "trailingAnnualDividendYield" viene
        # en fraccion (0.081 = 8,1%). Convertir con la regla del campo, nunca
        # por heuristica de magnitud.
        yld = _raw_number(quote.get("dividendYield"))
        if yld is not None:
            yld = yld / Decimal(100)
        else:
            yld = _raw_number(quote.get("trailingAnnualDividendYield"))
        exchange = quote.get("fullExchangeName") or quote.get("exchange")
        currency = quote.get("currency")
        out.append(
            RadarCandidate(
                symbol=symbol,
                name=quote.get("longName") or quote.get("shortName"),
                exchange=str(exchange) if exchange else None,
                currency=str(currency) if currency else None,
                price_to_book=_first_number(quote, ("priceToBookRatio", "priceBookRatio")),
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


def fetch_screener(query: dict[str, Any]) -> dict[str, Any]:
    """POST real al screener de Yahoo con sesion crumb (red, solo runtime)."""
    import httpx  # import diferido: los tests nunca tocan red

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
    payload = fetcher(build_screener_query(pb_max=pb_max, yield_min=yield_min, regions=regs, size=size))
    candidates = parse_screener_quotes(payload)
    if candidates:
        tickers = {c.symbol for c in candidates}
        # Company no es tenant-scoped (mismo precedente que deep_value_service).
        known = set(
            db.scalars(select(Company.ticker).where(Company.ticker.in_(tickers))).all()
        )
        for candidate in candidates:
            candidate.en_universo_propio = candidate.symbol in known
            candidate.via_cotejo = _via_cotejo(candidate)
    generado_en = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return candidates, generado_en, regs
