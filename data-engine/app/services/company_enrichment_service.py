"""Enrich Company master data from market-data APIs (Finnhub).

The company catalogue is a bootstrap seed, NOT the source of truth for
display names. When a Company's name is a placeholder (equals its ticker,
contains underscores, or is missing) or its exchange is unknown, we ask a
market-data API (Finnhub /stock/profile2) for the real name and metadata.
"""
from __future__ import annotations

import logging
import time
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Company

logger = logging.getLogger(__name__)

_PLACEHOLDER_EXCHANGES = {None, "", "UNKNOWN", "UNKNOWN_EXCHANGE"}

_PLACEHOLDER_SECTORS = {None, "", "Unknown", "UNKNOWN"}

# Enfriamiento entre intentos de enriquecimiento desde /companies/ensure:
# una ficha cuya industria Finnhub no esta en el mapa (p. ej. "Holding
# Companies") nunca se clasifica, y sin marca cada ensure volvia a llamar a
# Finnhub para siempre. El barrido manual (enrich_all) lo ignora: es el
# operador quien fuerza.
ENRICH_RETRY_COOLDOWN = timedelta(days=7)

# Mapeo declarado (GICS de 11 sectores) de los valores de `finnhubIndustry`
# observados en nuestro universo. Finnhub no expone sector: esto es una
# heuristica explicita y revisable, no un dato de la API.
# Regla de inclusion: solo entradas con una lectura GICS unica a nivel de
# sector. Los dos que senalo el auditor son correctos: "Retail" es el
# industry group GICS Retailing (sector Consumer Discretionary: ahi esta
# Amazon) y "Communications" es la industria Finnhub Communications
# Equipment (CSCO, ANET...), sector Information Technology. Las entradas
# ambiguas (p. ej. Finnhub "Consumer products", que mezcla Staples y
# Discretionary, o "Building", que mezcla Building Products y homebuilders)
# NO se mapean: industria no mapeada -> sector "Unknown" (honesto, nunca
# se inventa).
FINNHUB_INDUSTRY_TO_SECTOR: dict[str, str] = {
    "Aerospace & Defense": "Industrials",
    "Airlines": "Industrials",
    "Auto Components": "Consumer Discretionary",
    "Automobiles": "Consumer Discretionary",
    "Banking": "Financials",
    "Banks": "Financials",
    "Beverages": "Consumer Staples",
    "Biotechnology": "Health Care",
    "Chemicals": "Materials",
    "Commercial Services & Supplies": "Industrials",
    # Finnhub "Communications" es la industria GICS Communications Equipment
    # (CSCO, ANET, JNPR, FFIV...), sector Information Technology - no
    # Communication Services (los servicios llegan como Telecom/Telecommunication).
    "Communications": "Information Technology",
    "Construction": "Industrials",
    "Distributors": "Consumer Discretionary",
    "Diversified Consumer Services": "Consumer Discretionary",
    "Electrical Equipment": "Industrials",
    "Electric Utilities": "Utilities",
    "Energy": "Energy",
    "Financial Services": "Financials",
    "Food Products": "Consumer Staples",
    "Health Care": "Health Care",
    "Hotels, Restaurants & Leisure": "Consumer Discretionary",
    "Industrial Conglomerates": "Industrials",
    "Insurance": "Financials",
    "Leisure Products": "Consumer Discretionary",
    "Life Sciences Tools & Services": "Health Care",
    "Logistics & Transportation": "Industrials",
    "Machinery": "Industrials",
    "Marine": "Industrials",
    "Media": "Communication Services",
    "Metals & Mining": "Materials",
    "Oil & Gas Integrated": "Energy",
    "Packaging": "Materials",
    "Paper & Forest": "Materials",
    "Pharmaceuticals": "Health Care",
    "Professional Services": "Industrials",
    "Real Estate": "Real Estate",
    "Retail": "Consumer Discretionary",
    "Road & Rail": "Industrials",
    "Semiconductors": "Information Technology",
    "Technology": "Information Technology",
    "Telecom": "Communication Services",
    "Telecommunication": "Communication Services",
    "Textiles, Apparel & Luxury Goods": "Consumer Discretionary",
    "Tobacco": "Consumer Staples",
    "Trading Companies & Distributors": "Industrials",
    "Transportation Infrastructure": "Industrials",
    "Utilities": "Utilities",
}


def sector_for_industry(industry: str | None) -> str | None:
    """Devuelve el sector GICS declarado para una industria Finnhub, o None."""
    if not industry:
        return None
    return FINNHUB_INDUSTRY_TO_SECTOR.get(industry.strip())


class CompanyEnrichmentService:
    """Completa Company.name/exchange/sector/currency desde Finnhub."""

    def __init__(self, settings=None, client: httpx.Client | None = None) -> None:
        self.settings = settings or get_settings()
        self._client = client or httpx.Client(timeout=15)

    def close(self) -> None:
        self._client.close()

    # -- consulta a la API -------------------------------------------------
    def _finnhub_profile(self, ticker: str) -> dict | None:
        key = self.settings.finnhub_api_key
        if not key:
            logger.info("FINNHUB_API_KEY no configurada; sin enriquecimiento")
            return None
        try:
            resp = self._client.get(
                "https://finnhub.io/api/v1/stock/profile2",
                params={"symbol": ticker, "token": key},
            )
            if resp.status_code == 200:
                data = resp.json()
                if data and data.get("name"):
                    return data
        except httpx.HTTPError as exc:
            logger.warning("Finnhub profile2 fallo para %s: %s", ticker, exc)
        # Fallback: /search devuelve el nombre incluso para simbolos que
        # profile2 no cubre (p.ej. ADUR = Aduro Clean Technologies Inc).
        return self._finnhub_search(ticker)

    def _finnhub_search(self, ticker: str) -> dict | None:
        key = self.settings.finnhub_api_key
        if not key:
            return None
        try:
            resp = self._client.get(
                "https://finnhub.io/api/v1/search",
                params={"q": ticker, "token": key},
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            for item in data.get("result", []):
                symbol = (item.get("symbol") or "").upper()
                if symbol == ticker.upper():
                    description = (item.get("description") or "").strip()
                    if description:
                        return {"name": description}
            return None
        except httpx.HTTPError as exc:
            logger.warning("Finnhub search fallo para %s: %s", ticker, exc)
        return None

    # -- criterio de enriquecimiento --------------------------------------
    @staticmethod
    def needs_enrichment(company: Company) -> bool:
        # Sector en placeholder tambien dispara: antes solo miraba nombre y
        # exchange, asi que una ficha con nombre/exchange correctos y sector
        # "Unknown" quedaba "already_ok" para siempre (p.ej. CF Industries o
        # INVA en ProPicks, "Sin clasificar"). enrich() solo toca campos en
        # placeholder y nunca inventa: industria no mapeada -> sector Unknown.
        name = (company.name or "").strip()
        return (
            not name
            or name.upper() == (company.ticker or "").upper()
            or "_" in name
            or company.exchange in _PLACEHOLDER_EXCHANGES
            or company.sector in _PLACEHOLDER_SECTORS
        )

    # -- aplicacion ---------------------------------------------------------
    @staticmethod
    def _name_is_placeholder(company: Company) -> bool:
        name = (company.name or "").strip()
        return not name or name.upper() == (company.ticker or "").upper() or "_" in name

    @staticmethod
    def _in_cooldown(company: Company) -> bool:
        last = company.enrichment_attempted_at
        if last is None:
            return False
        # SQLite devuelve datetimes naive aunque la columna sea timezone=True.
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        return datetime.now(UTC) - last < ENRICH_RETRY_COOLDOWN

    def enrich(
        self,
        db: Session,
        company: Company,
        persist: bool = True,
        respect_cooldown: bool = False,
    ) -> bool:
        """Completa SOLO los campos en placeholder; los curados nunca se pisan.

        Con respect_cooldown=True (la via /companies/ensure), un intento
        reciente (ENRICH_RETRY_COOLDOWN) no llama a Finnhub otra vez: la
        marca se estampa en cada intento, haya o no cambios.

        needs_enrichment dispara por cualquier placeholder (nombre, exchange,
        sector), pero la escritura es campo a campo: una ficha curada con el
        sector en «Unknown» (Georgia Capital, LSE, GBP) no puede acabar con el
        nombre/bolsa/divisa del proveedor (auditor 2026-10-19: Finnhub devuelve
        GBX para LSE y pisar currency rompe los importes).
        """
        if not self.needs_enrichment(company):
            return False
        if respect_cooldown and self._in_cooldown(company):
            return False
        # Marca de intento ANTES de llamar: tambien cuenta el intento fallido
        # o sin datos; si no, una ficha inenriquecible reintentaria en cada
        # ensure dentro del mismo dia.
        company.enrichment_attempted_at = datetime.now(UTC)
        profile = self._finnhub_profile(company.ticker)
        if not profile:
            if persist:
                db.add(company)
            return False
        changed = False

        if self._name_is_placeholder(company):
            name = (profile.get("name") or "").strip()
            if name and name != company.name:
                company.name = name
                changed = True
        if company.exchange in _PLACEHOLDER_EXCHANGES:
            exchange = (profile.get("exchange") or "").strip()
            if exchange:
                company.exchange = exchange
                changed = True
        # industry no es visible en la UI: solo se actualiza cuando el sector
        # esta en placeholder y la industria es la pista para clasificarlo.
        # Con sector ya clasificado, el perfil no la pisa.
        industry = (profile.get("finnhubIndustry") or "").strip()
        if company.sector in _PLACEHOLDER_SECTORS and industry and industry.upper() not in {"N/A", "UNKNOWN"}:
            company.industry = industry
            changed = True
        if company.sector in _PLACEHOLDER_SECTORS:
            sector = sector_for_industry(company.industry)
            if sector:
                company.sector = sector
                changed = True
        if not (company.currency or "").strip():
            currency = (profile.get("currency") or "").strip()
            if currency:
                company.currency = currency
                changed = True

        if persist:
            db.add(company)
        return changed

    def enrich_all(self, db: Session, sleep_between: float = 0.8) -> dict:
        """Barre companies con datos debiles y las enriquece (respetando rate limit)."""
        rows = list(db.scalars(select(Company).order_by(Company.ticker)).all())
        enriched, skipped, not_found = 0, 0, 0
        for company in rows:
            if not self.needs_enrichment(company):
                skipped += 1
                continue
            if self.enrich(db, company):
                enriched += 1
            else:
                not_found += 1
            time.sleep(sleep_between)
        # enriched cubre los cambios y las marcas de intento de los fallidos:
        # not_found cuenta intentos sin datos, y toda llamada a enrich estampa
        # enrichment_attempted_at; commit si se llamo a la API al menos una vez.
        if enriched or not_found:
            db.commit()
        return {
            "total": len(rows),
            "enriched": enriched,
            "already_ok": skipped,
            "api_sin_datos": not_found,
        }


def fill_default_currency(company: Company) -> None:
    """Divisa de reserva si el proveedor no la dio: la del sufijo del ticker.

    ``.CO`` -> DKK, ``.L`` -> GBX, sin sufijo conocido -> USD. Solo toca una
    divisa vacía; nunca pisa la del proveedor ni la que mandó el cliente.
    """
    if (company.currency or "").strip():
        return
    from app.valuation.currency import listing_quote_unit

    company.currency = listing_quote_unit(company.ticker)


def ensure_company_stub(db: Session, ticker: str) -> Company:
    """Devuelve la Company para ticker, creando la ficha minima si no existe.

    El buscador resuelve tickers via Finnhub que aun no tienen fila en la BD;
    sin ficha, la generacion de tesis falla con "Unknown ticker" aunque la
    empresa exista. Mismo contrato que POST /companies/ensure: stub + enrich
    Finnhub best-effort (si falla, queda el stub; nunca rompe al caller).
    """
    ticker = ticker.strip().upper()
    company = db.scalar(select(Company).where(Company.ticker == ticker))
    if company is not None:
        return company
    company = Company(
        ticker=ticker,
        name=ticker,
        exchange="UNKNOWN",
        # Vacía a propósito: el enriquecimiento solo rellena la divisa vacía;
        # con "USD" una DKK/EUR/GBX nueva se quedaba en USD para siempre.
        currency="",
        sector="Unknown",
        industry="Unknown",
        company_type="research_candidate",
        valuation_model="unassigned",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    from app.seed import apply_master_taxonomy_to_stubs

    db.flush()
    apply_master_taxonomy_to_stubs(db)
    try:
        CompanyEnrichmentService().enrich(db, company)
    except Exception:  # noqa: BLE001 - el ensure nunca debe fallar por esto
        logger.warning("enrich fallo para %s", ticker, exc_info=True)
    fill_default_currency(company)
    db.commit()
    db.refresh(company)
    return company
