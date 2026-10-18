"""Reviewed ESEF issuer mapping beyond CNMV (ES).

Mismo contrato que cnmv_mapping: tabla revisada a mano, se extiende solo
tras verificar cada entrada contra el registro del regulador y el indice
ESEF; nunca se generan filas automaticamente y lo no resuelto queda
"unresolved", nunca adivinado.

ASML (NL) verificado 2026-10-19: LEI 724500Y6DUVHQD6OXN27 via GLEIF
("ASML Holding N.V.", NL) y filings.xbrl.org (entity id 1969, 5 filings
ESEF NL 2021-2025 con json_url; el filing 2024 lleva ifrs-full:ProfitLoss,
DilutedEarningsLossPerShare y BasicEarningsLossPerShare).
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


def _normalize(name: str) -> str:
    return " ".join(name.upper().replace(",", " ").split())


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


def resolve_ticker_for_country(country: str, entity_name: str) -> str | None:
    """Resuelve el nombre legal ESEF a ticker reviewed segun el pais del
    filing. ES usa la tabla CNMV; NL la tabla AFM/ESEF de este modulo."""
    if country == "ES":
        issuer = resolve_issuer(entity_name)
        return issuer.ticker if issuer else None
    if country == "NL":
        issuer = resolve_issuer_nl(entity_name)
        return issuer.ticker if issuer else None
    return None


def reviewed_tickers() -> list[str]:
    """Tickers reviewed de todos los paises cubiertos (ES + NL)."""
    return sorted(
        {i.ticker for i in REVIEWED_ISSUERS}
        | {i.ticker for i in REVIEWED_ISSUERS_NL}
    )
