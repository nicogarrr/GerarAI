"""Valuation engine registry — resolve company.valuation_model to an engine."""

from __future__ import annotations

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
    # El cambio de motor por identidad SOLO entra para tickers verificados a
    # mano (identidad comprobada 19 oct 2026 en prod). Mover por industria a
    # bancos/gestoras/REITs haria que motores fail-closed reemplazaran un DCF
    # que hoy da valor: se amplia solo cuando el motor tenga datos suficientes.
    ticker = (getattr(company, "ticker", "") or "").upper()
    verified_engines = {
        "CB": "insurer",  # Chubb: aseguradora (combined ratio, book value)
        "KKR": "holding_company",  # gestora: AUM/NAV, no FCF generico
        "CPT": "reit",  # Camden Property Trust: FFO/AFFO
        "BN": "holding_company",  # Brookfield (ya entraba por company_type)
        # Georgia Capital: entidad de inversion NIIF 10 (NAV = patrimonio).
        # Un DCF sobre su flujo de explotacion (-5,8 M GEL) no tiene sentido.
        "CGEO.L": "holding_company",
    }
    if ticker in verified_engines:
        return verified_engines[ticker]
    if "reit" in company_type:
        return "reit"
    return "standard_dcf"


def resolve(company: Company) -> ValuationEngine:
    key = resolve_engine_key(company)
    engine_cls = VALUATION_ENGINES.get(key, StandardDCFEngine)
    return engine_cls()


def list_engines() -> list[str]:
    return sorted(VALUATION_ENGINES.keys())
