"""Cobertura motor a motor de la batería de 7 (auditoría 4-nov-2026).

Para cada ticker de la batería (UBER, CHTR, UNH, Basic-Fit, ASTS, PLTR, TSLA)
se fija aquí, con empresas sintéticas y sin red:

1. Qué motor resuelve su clasificación (master o industria de proveedor) y
   que el método declarado no cae en un respaldo sin explicación.
2. Que sin datos el motor devuelve N/D honesto (``insufficient_data`` con los
   inputs que faltan nombrados), nunca una cifra inventada ni publicable.
3. Que el respaldo orientativo por múltiplos de un motor sectorial sin datos
   nunca sale publicable (blocker ``sector_engine_fallback``).

Regla de la casa: nada por empresa, todo general; los tickers de la batería
son aquí casos representativos de cada ruta, no un mapa escrito a mano.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.data.company_master import COMPANY_MASTER
from app.models.entities import Base, Company
from app.services.valuation_service import ValuationService
from app.valuation.engines.registry import (
    declared_engine_fallback,
    resolve_engine_key,
)

BATTERY = ("UBER", "CHTR", "UNH", "BFIT.AS", "ASTS", "PLTR", "TSLA")

# Clasificación master declarada -> motor que debe correr.
MASTER_EXPECTED_ENGINE = {
    "ASTS": "pre_revenue",  # probability_weighted_scenarios+dilution
    "UBER": "standard_dcf",  # platform_dcf+margin_expansion
    "PLTR": "standard_dcf",  # software_dcf+rule_of_40_context
    "TSLA": "scenario",  # scenario_auto_energy_fsd
}


def _master_entry(ticker: str) -> dict:
    return next(row for row in COMPANY_MASTER if row["ticker"] == ticker)


def _company(ticker: str, **overrides) -> Company:
    """Empresa sintética con la clasificación del master, sin sesión."""
    base = (
        _master_entry(ticker)
        if ticker in {r["ticker"] for r in COMPANY_MASTER}
        else {
            "ticker": ticker,
            "name": ticker,
            "exchange": "NYSE",
            "currency": "USD",
            "sector": "Unknown",
            "industry": "Unknown",
            "company_type": "research_candidate",
            "valuation_model": "unassigned",
            "special_sources": [],
            "special_risks": [],
            "factor_tags": [],
        }
    )
    row = {**base, **overrides}
    return Company(
        ticker=row["ticker"],
        name=row["name"],
        exchange=row["exchange"],
        currency=row["currency"],
        sector=row["sector"],
        industry=row["industry"],
        company_type=row["company_type"],
        valuation_model=row["valuation_model"],
        special_sources=row.get("special_sources") or [],
        special_risks=row.get("special_risks") or [],
        factor_tags=row.get("factor_tags") or [],
    )


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


# ---------------------------------------------------------------------------
# 1. Resolución de motor por ticker
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("ticker,expected", sorted(MASTER_EXPECTED_ENGINE.items()))
def test_master_battery_resolves_expected_engine(ticker, expected):
    assert resolve_engine_key(_company(ticker)) == expected


@pytest.mark.parametrize("ticker", sorted(MASTER_EXPECTED_ENGINE))
def test_master_battery_declared_model_is_served_without_fallback(ticker):
    """El método declarado corre de verdad o el motivo del respaldo queda."""
    company = _company(ticker)
    fallback = declared_engine_fallback(company, resolve_engine_key(company))
    assert fallback is None, fallback


@pytest.mark.parametrize(
    "ticker,industry",
    [
        # CHTR (Charter): cablera; ninguna taxonomía de proveedor la mueve
        # de un DCF de caja libre.
        ("CHTR", "Cable & Satellite"),
        ("CHTR", "Entertainment"),
        ("CHTR", "Telecom Services"),
        ("CHTR", "Media"),
        # UNH: managed care; las taxonomías habituales NO dicen «insurance».
        ("UNH", "Healthcare Plans"),
        ("UNH", "Health Care Plans"),
        ("UNH", "Managed Health Care"),
        ("UNH", "Health Care Providers & Services"),
        # Basic-Fit (BFIT.AS): gimnasios, ocio.
        ("BFIT.AS", "Leisure"),
        ("BFIT.AS", "Hotels, Restaurants & Leisure"),
        ("BFIT.AS", "Travel & Leisure"),
    ],
)
def test_watchlist_battery_industries_keep_standard_dcf(ticker, industry):
    assert resolve_engine_key(_company(ticker, industry=industry)) == "standard_dcf"


def test_unh_routing_depends_on_the_stored_industry_string():
    """UNH cambia de motor según la industria que guarde el proveedor.

    «Healthcare Plans» (Yahoo/FMP/GICS) -> standard_dcf; una etiqueta SIC
    tipo «Accident & Health Insurance» -> motor insurer, que sin combined
    ratio / ROE / g se niega y acaba en N/D o respaldo orientativo por
    múltiplos. El resultado visible de UNH depende de ese string: hay que
    verificar en prod cuál está guardado (instrument_reference / ficha).
    """
    dcf = _company("UNH", industry="Healthcare Plans")
    sic = _company("UNH", industry="Accident & Health Insurance")
    assert resolve_engine_key(dcf) == "standard_dcf"
    assert resolve_engine_key(sic) == "insurer"


# ---------------------------------------------------------------------------
# 2. N/D honesto sin datos (motor a motor de la batería)
# ---------------------------------------------------------------------------


def _assert_honest_nd(result: dict) -> None:
    assert result["status"] == "insufficient_data", result.get("trace", {}).get("notice")
    assert result["publishable"] is False
    assert result["missing_inputs"], "el N/D tiene que nombrar lo que falta"
    for key in ("expected_value", "bear_value", "base_value", "bull_value"):
        assert result.get(key) is None, f"{key} inventado: {result.get(key)}"


@pytest.mark.parametrize(
    "ticker,overrides",
    [
        ("UBER", {}),
        ("PLTR", {}),
        ("ASTS", {}),
        ("TSLA", {}),
        ("CHTR", {"industry": "Cable & Satellite"}),
        ("UNH", {"industry": "Healthcare Plans"}),
        (
            "BFIT.AS",
            {
                "industry": "Leisure",
                "exchange": "EURONEXT AMSTERDAM",
                "currency": "EUR",
            },
        ),
    ],
)
def test_battery_company_without_any_data_is_honest_nd(db, ticker, overrides):
    """Sin hechos, precio ni métricas: la batería entera devuelve N/D."""
    company = _company(ticker, **overrides)
    db.add(company)
    db.flush()
    result = ValuationService().value_company(db, company)
    _assert_honest_nd(result)


# ---------------------------------------------------------------------------
# 3. El respaldo por múltiplos de un motor sectorial nunca es publicable
# ---------------------------------------------------------------------------


def test_sector_engine_fallback_stays_unpublishable(db):
    """UNH enrutada a insurer (industria SIC) sin datos de aseguradora.

    El motor insurer se niega; el servicio intenta el respaldo orientativo
    por múltiplos. Sin peers tampoco da cifra y el N/D original se devuelve
    intacto; si diera cifra, llegaría siempre como ``partial`` no publicable
    con el blocker ``sector_engine_fallback``.
    """
    company = _company("UNH", industry="Accident & Health Insurance")
    db.add(company)
    db.flush()
    result = ValuationService().value_company(db, company)
    assert result["publishable"] is False
    if result["status"] == "insufficient_data":
        _assert_honest_nd(result)
    else:
        assert result["status"] == "partial"
        assert "sector_engine_fallback" in result["publication_blockers"]
