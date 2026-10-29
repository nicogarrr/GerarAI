"""Resolución de compañías por ticker con fallback de sufijo de mercado.

La píldora de búsqueda navega a /research/<displaySymbol> (SAN.MC, IBE.MC,
AIR.PA...) mientras el universo de research usa el ticker base (SAN, IBE,
AIR). Sin fallback, todas las rutas /api/companies/{ticker} devolvían 404
para acciones europeas llegando desde el buscador.

Reglas:
- El match exacto siempre gana (BRK.B, BF.A y tickers reales con punto
  nunca se tocan).
- El fallback solo aplica cuando el exacto falla y el sufijo es un mercado
  conocido (mismo mapa que el frontend usa para etiquetar la bolsa).
- Nunca crea ni inventa compañías: miss -> None, y el caller decide (404).
"""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company


def _reference_company_candidates(db: Session, normalized: str) -> list[str]:
    """Tickers Company candidatos via la tabla de referencia (seam aditivo).

    Consulta instrument_references primero: si el ticker pedido tiene fila
    con FIGI, devuelve todos los tickers que comparten ese FIGI (o su
    composite) para que un renombre resuelva a la misma Company. Sin fila
    o sin FIGI: lista vacia (el fallback de sufijos sigue exacto igual).
    Degrada a [] si la tabla aun no existe (DB anterior a la migracion).
    """
    try:
        from app.models.entities import InstrumentReference
    except Exception:
        return []
    try:
        row = db.scalar(
            select(InstrumentReference).where(
                InstrumentReference.ticker_normalized == normalized
            )
        )
    except Exception:
        return []
    if row is None:
        return []
    candidates: set[str] = set()
    try:
        if row.figi:
            for sib in db.scalars(
                select(InstrumentReference).where(InstrumentReference.figi == row.figi)
            ).all():
                candidates.add(sib.ticker_normalized)
        if row.composite_figi:
            for sib in db.scalars(
                select(InstrumentReference).where(
                    InstrumentReference.composite_figi == row.composite_figi
                )
            ).all():
                candidates.add(sib.ticker_normalized)
    except Exception:
        return []
    candidates.discard(normalized)
    return sorted(candidates)

# Clase de acción US con el separador "otro": Yahoo/EDGAR nombran las
# clases con guion (BRK-B) y el master/Finnhub con punto (BRK.B). Si el
# usuario pide una variante, se prueba la otra SOLO contra filas existentes
# del master: nunca crea identidad nueva, y el match exacto sigue ganando.
_US_SHARE_CLASS_DASHED = re.compile(r"^([A-Z0-9]{1,5})-([AB])$")
_US_SHARE_CLASS_DOTTED = re.compile(r"^([A-Z0-9]{1,5})\.([AB])$")


def _share_class_variants(normalized: str) -> list[str]:
    """Variantes de separador de clase US (BRK-B <-> BRK.B), o lista vacía."""
    variants: list[str] = []
    for pattern, separator in (
        (_US_SHARE_CLASS_DASHED, "."),
        (_US_SHARE_CLASS_DOTTED, "-"),
    ):
        match = pattern.fullmatch(normalized)
        if match:
            variants.append(f"{match.group(1)}{separator}{match.group(2)}")
    return variants


KNOWN_MARKET_SUFFIXES = frozenset({
    "MC",  # Bolsa de Madrid
    "L",   # London
    "PA",  # Euronext Paris
    "AS",  # Euronext Amsterdam
    "BR",  # Euronext Brussels
    "LS",  # Euronext Lisbon
    "DE",  # XETRA
    "F",   # Frankfurt
    "MI",  # Borsa Italiana
    "SW",  # SIX
    "VI",  # Wiener Börse
    "HE",  # Nasdaq Helsinki
    "ST",  # Nasdaq Stockholm
    "CO",  # Nasdaq Copenhagen
    "OL",  # Oslo Børs
    "HK",  # HKEX
    "T",   # Tokyo
    "AX",  # ASX
    "TO",  # TSX
    "V",   # TSXV
    "MX",  # BMV
    "SA",  # B3
})


def _base_contradicts_listing(requested: str, company: Company | None) -> bool:
    """True when ``requested`` is a reviewed listing and ``company`` is another issuer.

    BFIT.AS is Basic-Fit (ISIN NL0011872650); its bare base ticker BFIT is a
    US homonym. The suffix fallback must not hand a Basic-Fit request the US
    row: only a base row carrying the listing's own ISIN is the same issuer.
    """
    if company is None:
        return False
    from app.services.listing_identity import BY_ISIN

    for listing in BY_ISIN.values():
        if listing.ticker == requested:
            return (company.isin or "").strip().upper() != listing.isin
    return False


def resolve_company(db: Session, ticker: str) -> Company | None:
    """Devuelve la Company por ticker exacto o, si falla y hay sufijo de
    mercado conocido, por ticker base. None si no existe.

    Seam aditivo: antes del fallback de sufijos se consulta la tabla de
    referencia (identidad FIGI estable). Si no hay fila, el fallback
    funciona exacto igual que hoy; un desconocido sigue siendo None.
    """
    normalized = ticker.strip().upper()
    company = db.scalar(select(Company).where(Company.ticker == normalized))
    if company is not None:
        return company
    for candidate in _reference_company_candidates(db, normalized):
        company = db.scalar(select(Company).where(Company.ticker == candidate))
        if company is not None:
            return company
    for variant in _share_class_variants(normalized):
        company = db.scalar(select(Company).where(Company.ticker == variant))
        if company is not None:
            return company
    if "." not in normalized:
        return None
    base, _, suffix = normalized.rpartition(".")
    if not base or suffix not in KNOWN_MARKET_SUFFIXES:
        return None
    company = db.scalar(select(Company).where(Company.ticker == base))
    if _base_contradicts_listing(normalized, company):
        return None
    return company


def resolve_companies(
    db: Session, tickers: list[str]
) -> tuple[list[Company], list[str]]:
    """Resuelve N tickers con la politica de ``resolve_company`` en 1-2 queries.

    Misma politica: el match exacto siempre gana (BRK.B, BF.A y tickers
    reales con punto nunca se tocan) y el fallback a ticker base solo
    aplica con sufijo de mercado conocido. Un IN para los exactos y, solo
    si hay alias pendientes, un segundo IN para sus bases. Seam aditivo:
    entre el exacto y el fallback de sufijos se consulta la referencia
    (identidad FIGI); sin fila, el fallback funciona exacto igual que hoy.
    Devuelve las Company en el orden pedido (deduplicadas por id) y los
    tickers sin match, en orden. Nunca crea ni inventa compañías.
    """
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in tickers:
        ticker = raw.strip().upper()
        if ticker and ticker not in seen:
            seen.add(ticker)
            normalized.append(ticker)
    if not normalized:
        return [], []
    exact = {
        company.ticker: company
        for company in db.scalars(
            select(Company).where(Company.ticker.in_(normalized))
        ).all()
    }
    alias_bases = {}  # ticker pedido -> ticker base candidato
    for ticker in normalized:
        if ticker in exact:
            continue
        variants = _share_class_variants(ticker)
        if variants:
            alias_bases[ticker] = variants[0]
            continue
        if "." not in ticker:
            continue
        base, _, suffix = ticker.rpartition(".")
        if base and suffix in KNOWN_MARKET_SUFFIXES:
            alias_bases[ticker] = base
    bases = {}
    if alias_bases:
        bases = {
            company.ticker: company
            for company in db.scalars(
                select(Company).where(
                    Company.ticker.in_(sorted(set(alias_bases.values())))
                )
            ).all()
        }
    # Seam aditivo: solo para los tickers que siguen sin match tras el
    # exacto, expandir por FIGI via la referencia (queries extra solo si
    # hay pendientes; sin fila, todo queda igual que hoy).
    reference_hit: dict[str, Company] = {}
    pending = [t for t in normalized if t not in exact]
    if pending:
        try:
            from app.models.entities import InstrumentReference

            rows = list(
                db.scalars(
                    select(InstrumentReference).where(
                        InstrumentReference.ticker_normalized.in_(pending)
                    )
                ).all()
            )
            wanted: dict[str, set[str]] = {}
            for row in rows:
                figs = {f for f in (row.figi, row.composite_figi) if f}
                if figs:
                    wanted[row.ticker_normalized] = figs
            figis: set[str] = set()
            for figs in wanted.values():
                figis.update(figs)
            if figis:
                siblings = list(
                    db.scalars(
                        select(InstrumentReference).where(
                            (InstrumentReference.figi.in_(sorted(figis)))
                            | (InstrumentReference.composite_figi.in_(sorted(figis)))
                        )
                    ).all()
                )
                by_figi: dict[str, list[str]] = {}
                for sib in siblings:
                    for figi in (sib.figi, sib.composite_figi):
                        if figi in figis:
                            by_figi.setdefault(figi, []).append(sib.ticker_normalized)
                sibling_tickers = {sib.ticker_normalized for sib in siblings}
                by_ticker = (
                    {
                        company.ticker: company
                        for company in db.scalars(
                            select(Company).where(
                                Company.ticker.in_(sorted(sibling_tickers))
                            )
                        ).all()
                    }
                    if sibling_tickers
                    else {}
                )
                for ticker in pending:
                    for figi in wanted.get(ticker, set()):
                        for cand in by_figi.get(figi, []):
                            if cand in by_ticker:
                                reference_hit[ticker] = by_ticker[cand]
                                break
                        if ticker in reference_hit:
                            break
        except Exception:
            reference_hit = {}
    companies: list[Company] = []
    resolved_ids: set[int] = set()
    missing: list[str] = []
    for ticker in normalized:
        base_company = bases.get(alias_bases.get(ticker, ""))
        if _base_contradicts_listing(ticker, base_company):
            base_company = None
        company = exact.get(ticker) or reference_hit.get(ticker) or base_company
        if company is None:
            missing.append(ticker)
        elif company.id not in resolved_ids:
            resolved_ids.add(company.id)
            companies.append(company)
    return companies, missing
