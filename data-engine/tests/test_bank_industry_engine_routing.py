"""Bancos por industria: motor bank (P/B justificado), nunca un FCFF DCF.

Prod, 4-nov-2026 (tenant 2): Banco Santander (industry «Banking», company_type
«research_candidate», valuation_model «unassigned») salía con valor razonable
232,48 € frente a 10,39 € de precio. El registro solo movía de motor por
industria a las aseguradoras, así que el banco caía en el DCF estándar: un
FCFF sobre «ingresos» de 112.735 M con un margen FCF «normalizado» que
convergía del −15,8 % al 44,5 % (el flujo operativo de un banco mueve depósitos
y créditos, no es caja libre). Pasa con cualquier banco dado de alta desde la
watchlist (BBVA «Banks», JPM «Banking»…), no solo con SAN.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import FinancialFact
from app.models.entities import Base
from app.services.valuation_service import ValuationService
from app.valuation.engines.registry import resolve_engine_key
from tests.test_valgrandes_normalized_fcf import AMZN, M, _seed


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def _co(industry: str, **kw) -> SimpleNamespace:
    base = dict(ticker="XBANK", valuation_model="unassigned", factor_tags=[],
                company_type="research_candidate", industry=industry)
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.mark.parametrize("industry", ["Banking", "Banks", "Banks - Regional", "Banks - Diversified"])
def test_any_bank_industry_resolves_to_the_bank_engine(industry):
    assert resolve_engine_key(_co(industry)) == "bank"


@pytest.mark.parametrize(
    "industry", ["Electric Utilities", "Software", "Asset Management", "Financial Services", "Unknown"]
)
def test_non_bank_industries_keep_their_engine(industry):
    assert resolve_engine_key(_co(industry)) == "standard_dcf"


def test_explicit_engines_still_win_over_the_bank_industry():
    assert resolve_engine_key(_co("Banks", company_type="asset_manager_holding")) == "holding_company"
    assert resolve_engine_key(_co("Banks", valuation_model="sotp")) == "sotp"


def _fact(db, company, metric, value, year=2025, unit="EUR"):
    db.add(
        FinancialFact(
            company_id=company.id, metric=metric, value=Decimal(str(value)), unit=unit,
            period=f"{year}-12-31:FY", fiscal_year=year, fiscal_quarter="FY",
            source_type="ESEF", is_reported=True, confidence=Decimal("0.90"),
        )
    )


def _bank(db, ticker: str):
    # Historial con el que el DCF estándar sí daba cifra (capex normalizado +
    # multietapa), etiquetado como banco por el proveedor.
    company = _seed(db, ticker, AMZN, shares=10_827 * M, net_debt=-5_233 * M, price=10.39, wacc=0.10)
    company.industry = "Banking"
    db.commit()
    return company


def test_bank_without_bank_inputs_is_not_valued_with_a_free_cash_flow_dcf(db):
    company = _bank(db, "SANX")
    result = ValuationService().value_company(db, company)
    assert result["trace"]["resolved_engine"] == "bank"
    assert result["trace"].get("method") != "fcff_dcf"
    # Sin book tangible ni ROE/CoE/crecimiento declarados (y sin peers para el
    # respaldo por múltiplos): N/D, nunca el DCF de caja libre.
    assert result["status"] != "ok"
    assert result.get("expected_value") is None
    assert result.get("publishable") is False


def test_bank_with_sourced_book_inputs_gets_a_justified_price_to_book_value(db):
    company = _bank(db, "SANY")
    shares = 10_827 * M
    for metric, value, unit in [
        ("tangible_book_value", 9.0 * shares, "USD"),
        ("return_on_tangible_equity", 0.15, "decimal"),
        ("cost_of_equity", 0.11, "decimal"),
        ("book_value_growth", 0.04, "decimal"),
    ]:
        _fact(db, company, metric, value, unit=unit)
    db.commit()
    result = ValuationService().value_company(db, company)
    assert result["trace"]["resolved_engine"] == "bank"
    # P/B = (ROE − g)/(CoE − g) = 0,11/0,07 ≈ 1,571 sobre 9,00 de book tangible por acción.
    assert result["base_value"] == pytest.approx(9.0 * (0.15 - 0.04) / (0.11 - 0.04), rel=1e-6)
    assert result["base_value"] < 3 * 9.0
