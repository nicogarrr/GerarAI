"""Valuation engine registry — resolve company.valuation_model to an engine."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import object_session

from app.models import Company
from app.services.company_types import is_holding_company_type
from app.valuation.engines.base import ValuationEngine
from app.valuation.engines.commodity import CommodityCycleEngine
from app.valuation.engines.holding_company import HoldingCompanyEngine
from app.valuation.engines.pre_revenue import PreRevenueScenarioEngine
from app.valuation.engines.sector_specific import (
    BankValuationEngine,
    InsurerValuationEngine,
    ReitValuationEngine,
)
from app.valuation.engines.sotp_engine import SOTPEngine
from app.valuation.engines.standard_dcf import StandardDCFEngine

VALUATION_ENGINES: dict[str, type[ValuationEngine]] = {
    "standard_dcf": StandardDCFEngine,
    "sotp": SOTPEngine,
    "pre_revenue": PreRevenueScenarioEngine,
    "holding_company": HoldingCompanyEngine,
    "commodity": CommodityCycleEngine,
    "bank": BankValuationEngine,
    "insurer": InsurerValuationEngine,
    "reit": ReitValuationEngine,
}


_REIT_RE = re.compile(r"\breits?\b|real estate investment trust", re.IGNORECASE)


def is_equity_reit_industry(industry: str | None) -> bool:
    """«REIT» como palabra (o «real estate investment trust»), sin hipotecarios."""
    value = (industry or "").lower()
    return bool(_REIT_RE.search(value)) and "mortgage" not in value


def reference_industry(company: Company) -> str | None:
    """Industria de la referencia del instrumento (financedatabase), o None.

    Solo con una empresa ligada a una sesión (los dobles de test no la
    tienen) y solo si la divisa coincide: el mismo símbolo en otra bolsa es
    otro instrumento. Se guarda en la instancia para no repetir la consulta
    en cada llamada del mismo cálculo.
    """
    try:
        instance_dict: dict[str, Any] = vars(company)
    except TypeError:
        instance_dict = {}
    if "_engine_reference_industry" in instance_dict:
        return instance_dict["_engine_reference_industry"]
    industry: str | None = None
    try:
        db = object_session(company)
    except Exception:
        db = None
    ticker = getattr(company, "ticker", None)
    if db is not None and ticker:
        from app.services.instrument_reference import get_by_ticker

        # Sin autoflush: resolver el motor no debe volcar cambios pendientes
        # de quien llama (p. ej. a mitad de una ingesta).
        with db.no_autoflush:
            row = get_by_ticker(db, ticker)
        if row is not None and row.industry:
            ref_currency = (row.currency or "").upper()
            own_currency = (getattr(company, "currency", None) or "").upper()
            if not ref_currency or not own_currency or ref_currency == own_currency:
                industry = row.industry
        instance_dict["_engine_reference_industry"] = industry
    return industry


def resolve_engine_key(company: Company) -> str:
    model = (company.valuation_model or "").lower()
    tags = set(company.factor_tags or [])
    company_type = (company.company_type or "").lower()
    is_holding = is_holding_company_type(company_type)

    if (
        "sotp" in model
        or "sotp" in tags
        or is_holding
    ):
        if is_holding:
            return "holding_company"
        return "sotp"
    if "commodity" in model or "commodities" in tags or "mining" in company_type or "uranium" in company_type:
        return "commodity"
    if (
        "pre_fcf" in tags
        or "speculative" in tags
        or "pre_revenue" in company_type
        or "speculative" in model
        or "nav_rough" in model
        or "probability_weighted_scenarios" in model
    ):
        return "pre_revenue"
    if "bank" in company_type or model.startswith("bank"):
        return "bank"
    if "insurer" in company_type or "insurance" in company_type:
        return "insurer"
    # Las altas por watchlist/enriquecimiento dejan company_type en
    # "research_candidate" y la clasificacion real solo vive en el industry del
    # proveedor. Un FCFF DCF sobre una aseguradora no tiene sentido (el flujo
    # operativo incluye float de reservas), asi que el motor correcto es el
    # insurer, que se niega declarando combined_ratio/roe/g si no estan.
    industry = (getattr(company, "industry", None) or "").lower()
    if "insurance" in industry and "broker" not in industry:
        return "insurer"
    # Lo mismo para bancos («Banks - Regional», «Banks», «Banking»): el flujo
    # operativo de un banco mueve depósitos y créditos, no es caja libre, y un
    # FCFF DCF sobre él inventa cifras (SAN, 3-nov-2026: 232 € frente a 10 €
    # de precio, con un margen FCF «normalizado» del 44 %). El marco de la
    # empresa ya lo trata como banco (company_framework); el motor tiene que
    # ser el mismo. Si al motor bank le faltan datos, valuation_service pasa
    # al respaldo orientativo por múltiplos (no publicable) o deja N/D, nunca
    # un DCF de caja libre.
    if "bank" in industry:
        return "bank"
    # REITs de renta por industria: la de la ficha (FMP/Yahoo «REIT -
    # Residential», GICS «... (REITs)») o, cuando esa es la taxonomía gruesa
    # de Finnhub («Real Estate», la que hay en prod para CPT, O, PLD), la de
    # la referencia del instrumento («Residential REITs»). Un FCFF DCF sobre
    # un REIT ignora que reparte casi todo su beneficio y se valora por NAV
    # (NOI / cap rate); si al motor reit le faltan datos, valuation_service
    # pasa al respaldo orientativo por múltiplos o deja N/D. Los REITs
    # hipotecarios no van aquí: su activo son préstamos, no inmuebles con NOI.
    if is_equity_reit_industry(industry) or is_equity_reit_industry(
        reference_industry(company)
    ):
        return "reit"
    # Residuo sin regla general todavía: gestoras alternativas y holdings de
    # inversión. Su industria en los perfiles guardados es la misma que la de
    # bolsas, brokers o pagos («Financial Services» / «Capital Markets»), así
    # que una regla por industria movería también a V, MA o CME. Se quedan
    # aquí hasta que exista una señal de datos (company_type clasificado o
    # NAV/AUM ingeridos). Aseguradoras (CB) y REITs (CPT) ya salen por reglas.
    ticker = (getattr(company, "ticker", "") or "").upper()
    pending_general_rule = {
        "KKR": "holding_company",  # gestora alternativa: AUM/NAV, no FCF genérico
        "BN": "holding_company",  # Brookfield: holding + gestora
        # Georgia Capital: entidad de inversión NIIF 10 (NAV = patrimonio).
        # Un DCF sobre su flujo de explotación (-5,8 M GEL) no tiene sentido.
        "CGEO.L": "holding_company",
    }
    if ticker in pending_general_rule:
        return pending_general_rule[ticker]
    if "reit" in company_type:
        return "reit"
    return "standard_dcf"


def resolve(company: Company) -> ValuationEngine:
    key = resolve_engine_key(company)
    engine_cls = VALUATION_ENGINES.get(key, StandardDCFEngine)
    return engine_cls()


def list_engines() -> list[str]:
    return sorted(VALUATION_ENGINES.keys())
