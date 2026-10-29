"""Reviewed ESEF issuer mapping beyond CNMV (ES).

Mismo contrato que cnmv_mapping: tabla revisada a mano, se extiende solo
tras verificar cada entrada contra el registro del regulador y el indice
ESEF; nunca se generan filas automaticamente y lo no resuelto queda
"unresolved", nunca adivinado.

ASML (NL) verificado 2026-10-19: LEI 724500Y6DUVHQD6OXN27 via GLEIF
("ASML Holding N.V.", NL) y filings.xbrl.org (entity id 1969, 5 filings
ESEF NL 2021-2025 con json_url; el filing 2024 lleva ifrs-full:ProfitLoss,
DilutedEarningsLossPerShare y BasicEarningsLossPerShare).

Kerry Group (IE) verificado 2026-10-19: filings.xbrl.org NO indexa Irlanda
(filter[country]=IE devuelve 0 filings), asi que entra por paquete ESEF del
propio emisor (ver esef_package_sources). LEI 635400TLVVBNXLFHWC59 via GLEIF
("KERRY GROUP PUBLIC LIMITED COMPANY", IE; ISINs IE0004906560 ordinaria y
US4924601002 ADR) y confirmado dentro del paquete ESEF FY2025
(xbrli:identifier con esquema ISO 17442 + nombre legal declarado).

CORRECCION 2026-10-19 (colision de ticker): la entrada ligaba KRKNF a Kerry
por la premisa de que KRKNF era Kerry, sin verificarlo. KRKNF es Kraken
Robotics Inc (TSX-V: PNG, OTCQB: KRKNF; krakenrobotics.com/investors), una
empresa canadiense distinta que NO presenta ESEF. Tickers reales de Kerry
verificados contra kerry.com/investors/faq: KYGa.I (Euronext Dublin) y
KYGa.L (LSE); en EEUU solo ADR OTC KRYAY (CUSIP 492460100, BNY, ratio 1:1)
y ordinaria OTC KRYAF (otcmarkets.com). Ticker reviewed: KRYAY.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.services.cnmv_mapping import REVIEWED_ISSUERS, resolve_issuer


@dataclass(frozen=True)
class ReviewedEsefIssuer:
    ticker: str
    legal_name: str
    lei: str
    isin: str
    country: str
    aliases: tuple[str, ...] = field(default=())


REVIEWED_ISSUERS_NL: tuple[ReviewedEsefIssuer, ...] = (
    ReviewedEsefIssuer(
        "ASML", "ASML Holding N.V.", "724500Y6DUVHQD6OXN27",
        "NL0010273215", "NL", ("ASML HOLDING NV", "ASML.AS"),
    ),
)


REVIEWED_ISSUERS_IE: tuple[ReviewedEsefIssuer, ...] = (
    ReviewedEsefIssuer(
        "KRYAY", "Kerry Group Public Limited Company", "635400TLVVBNXLFHWC59",
        "IE0004906560", "IE",
        ("KERRY GROUP PLC", "KERRY GROUP", "KYGA", "KYGA.L", "KYGA.I",
         "KRZ", "KRZ.IR", "KRYAF"),
    ),
)


# Misma clave que cnmv_mapping (acentos y puntos plegados): una sola
# implementacion para que las formas societarias se normalicen igual en ES/NL/IE.
from app.services.cnmv_mapping import _normalize


def resolve_issuer_nl(query: str) -> ReviewedEsefIssuer | None:
    """Ticker/ISIN/LEI/nombre legal exacto -> emisor NL revisado.

    None cuando no hay match o es ambiguo: nunca se adivina. No se intentan
    matches parciales (mismo criterio que cnmv_mapping.resolve_issuer).
    """
    q = _normalize(query)
    if not q:
        return None
    matches = []
    for issuer in REVIEWED_ISSUERS_NL:
        keys = {
            issuer.ticker.upper(),
            issuer.isin.upper(),
            issuer.lei.upper(),
            _normalize(issuer.legal_name),
        }
        keys |= {_normalize(a) for a in issuer.aliases}
        if q in keys:
            matches.append(issuer)
    return matches[0] if len(matches) == 1 else None


def resolve_issuer_ie(query: str) -> ReviewedEsefIssuer | None:
    """Ticker/ISIN/LEI/nombre legal exacto -> emisor IE revisado.

    None cuando no hay match o es ambiguo: nunca se adivina."""
    q = _normalize(query)
    if not q:
        return None
    matches = []
    for issuer in REVIEWED_ISSUERS_IE:
        keys = {
            issuer.ticker.upper(),
            issuer.isin.upper(),
            issuer.lei.upper(),
            _normalize(issuer.legal_name),
        }
        keys |= {_normalize(a) for a in issuer.aliases}
        if q in keys:
            matches.append(issuer)
    return matches[0] if len(matches) == 1 else None


def resolve_issuer_by_lei(lei: str) -> ReviewedEsefIssuer | None:
    """LEI exacto -> emisor reviewed de cualquier pais (paquetes ESEF del
    emisor, donde la identidad la fija el propio zip)."""
    q = (lei or "").strip().upper()
    if not q:
        return None
    matches = [
        i for i in REVIEWED_ISSUERS_NL + REVIEWED_ISSUERS_IE if i.lei.upper() == q
    ]
    return matches[0] if len(matches) == 1 else None


def resolve_ticker_for_country(country: str, entity_name: str) -> str | None:
    """Resuelve el nombre legal ESEF a ticker reviewed segun el pais del
    filing. ES usa la tabla CNMV; NL/IE las tablas revisadas de este modulo."""
    if country == "ES":
        issuer = resolve_issuer(entity_name)
        return issuer.ticker if issuer else None
    if country == "NL":
        issuer = resolve_issuer_nl(entity_name)
        return issuer.ticker if issuer else None
    if country == "IE":
        issuer = resolve_issuer_ie(entity_name)
        return issuer.ticker if issuer else None
    return None


def _alias_is_name(alias: str, ticker: str) -> bool:
    """Un alias solo cuenta como NOMBRE si tiene contenido de nombre: varias
    palabras («KERRY GROUP PLC») o un token de >=4 letras distinto del ticker
    y sin punto («INDITEX», «TELEFONICA»). Los aliases tipo ticker de bolsa
    («ARM.MC», «TEF.MC», «ASML.AS») NO son nombres: su token es el propio
    ticker y reintroduciria por la puerta de atras la colision global de
    tickers que la guardia company_mismatch existe para bloquear (caso real:
    «ARM.MC» rescatando a Arm Holdings como si fuera Arima)."""
    a = (alias or "").strip()
    if not a or "." in a:
        return False
    if " " in a:
        return True
    return len(a) >= 4 and a.upper() != ticker.upper()


def reviewed_names_for_ticker(ticker: str) -> set[str]:
    """Nombres reviewed (legal + alias COMO NOMBRE) ligados a un ticker del
    manifest ESEF. Los aliases tipo TICKER.XX quedan fuera (_alias_is_name).

    Prueba de identidad para la guardia company_mismatch de refresh_from_esef:
    el nombre corto comercial de una Company (p.ej. «Inditex») no comparte
    tokens con el nombre legal del filing («INDUSTRIA DE DISENO TEXTIL, S.A.»),
    pero si con el alias reviewed («INDITEX»). Ticker desconocido -> conjunto
    vacio: la guardia decide solo con el entity_name del snapshot."""
    t = (ticker or "").strip().upper()
    if not t:
        return set()
    names: set[str] = set()
    for issuer in REVIEWED_ISSUERS:
        if issuer.ticker.upper() == t:
            names.add(issuer.legal_name)
            names.update(a for a in issuer.aliases if _alias_is_name(a, t))
    for issuer in REVIEWED_ISSUERS_NL + REVIEWED_ISSUERS_IE:
        if issuer.ticker.upper() == t:
            names.add(issuer.legal_name)
            names.update(a for a in issuer.aliases if _alias_is_name(a, t))
    return names


# ISINs de valores conocidos del mismo emisor reviewed (p. ej. ordinaria
# Euronext + ADR OTC de Kerry son el MISMO issuer con dos securities).
_REVIEWED_EXTRA_ISINS: dict[str, tuple[str, ...]] = {
    "KRYAY": ("US4924601002",),  # ADR OTC de Kerry Group (GLEIF), mismo LEI
}


def reviewed_isins_for_ticker(ticker: str) -> frozenset[str]:
    """Conjunto de ISINs reviewed aceptados para el ticker (emisor ESEF).

    Incluye el ISIN primario del filing mas securities verificadas del mismo
    emisor (ADR). Conjunto vacio cuando el ticker no es reviewed.
    """
    t = (ticker or "").strip().upper()
    if not t:
        return frozenset()
    isins = set(_REVIEWED_EXTRA_ISINS.get(t, ()))
    for issuer in REVIEWED_ISSUERS:
        if issuer.ticker.upper() == t and issuer.isin:
            isins.add(issuer.isin.strip().upper())
    for issuer in REVIEWED_ISSUERS_NL + REVIEWED_ISSUERS_IE:
        if issuer.ticker.upper() == t and issuer.isin:
            isins.add(issuer.isin.strip().upper())
    return frozenset(isins)


def reviewed_isin_for_ticker(ticker: str) -> str | None:
    """ISIN reviewed del ticker ESEF (prueba de identidad fuerte), o None."""
    t = (ticker or "").strip().upper()
    if not t:
        return None
    for issuer in REVIEWED_ISSUERS:
        if issuer.ticker.upper() == t:
            return issuer.isin
    for issuer in REVIEWED_ISSUERS_NL + REVIEWED_ISSUERS_IE:
        if issuer.ticker.upper() == t:
            return issuer.isin
    return None


def reviewed_tickers() -> list[str]:
    """Tickers reviewed de todos los paises cubiertos (ES + NL + IE)."""
    return sorted(
        {i.ticker for i in REVIEWED_ISSUERS}
        | {i.ticker for i in REVIEWED_ISSUERS_NL}
        | {i.ticker for i in REVIEWED_ISSUERS_IE}
    )
