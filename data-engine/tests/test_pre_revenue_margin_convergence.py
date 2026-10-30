"""RKLB (30-oct-2026): growth con margen inmaduro no es Meta/Microsoft.

Un «valor justo -94 %» venía de aplicar un DCF de margen constante a una
empresa que quema caja hoy. Método: DCF con CONVERGENCIA de margen — del
margen FCF reportado (hecho, negativo) al objetivo de madurez en 5 años —
solo cuando el objetivo es un InferredInput validado (base explícita + URLs
https). Orientativo siempre (blocker inferred_fcf_margin_target); sin
objetivo con fuente, N/D explicado. Nada se inventa.
"""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base as CoreBase  # noqa: F401  (registra listeners)
from app.models.entities import Base, Company
from app.services.inferred_input_service import InferredInputService
from app.valuation.dcf_fcff import ConvergenceDCFInputs, run_dcf_margin_convergence
from app.valuation.engines.base import ValuationContext
from app.valuation.engines.pre_revenue import PreRevenueScenarioEngine
from tests.test_inferred_global_coherent_wiring import _Snap

BASE = "Dado el margen FCF medio de pares aeroespaciales maduros con fuentes SEC, inferimos 0,15"
URLS = ["https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=RKLB"]


@pytest.fixture()
def engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


# Tipo RKLB: ingresos 400 M creciendo 30 %, FCF -100 M (margen -25 %), caja neta.
VALUES = {
    "revenue": 400_000_000.0,
    "free_cash_flow": -100_000_000.0,
    "revenue_growth": 0.30,
    "shares_diluted": 500_000_000.0,
    "net_debt": -500_000_000.0,
}


def _company(db, ticker="RKLB"):
    db.info.setdefault("tenant_id", 2)
    c = Company(ticker=ticker, name=ticker, exchange="NASDAQ", company_type="growth",
                valuation_model="pre_revenue", factor_tags=["pre_fcf"])
    db.add(c)
    db.commit()
    return c


def _value(db, company, values=None, price=20.0):
    ctx = ValuationContext(db=db, company=company, snapshot=_Snap(values or VALUES),
                           current_price=price, engine_key="pre_revenue")
    return PreRevenueScenarioEngine().value(ctx)


def test_convergence_math_linear_path_and_terminal_on_converged_margin():
    result = run_dcf_margin_convergence(
        ConvergenceDCFInputs(
            revenue=100.0, revenue_growth=0.0, initial_fcf_margin=-0.20,
            target_fcf_margin=0.20, wacc=0.12, terminal_growth=0.03,
            net_debt=0.0, shares_outstanding=10.0, years=4,
        )
    )
    margins = [row["fcf_margin"] for row in result.forecast]
    assert margins == pytest.approx([-0.10, 0.0, 0.10, 0.20])
    # Terminal sobre el FCF convergido del último año (100 * 0,20 = 20).
    assert result.trace["terminal_fcf"] == pytest.approx(20.0 * 1.03)


def test_convergence_refuses_when_terminal_year_still_burns():
    with pytest.raises(ValueError, match="converged fcf"):
        run_dcf_margin_convergence(
            ConvergenceDCFInputs(
                revenue=100.0, revenue_growth=0.0, initial_fcf_margin=-0.50,
                target_fcf_margin=-0.10, wacc=0.12, terminal_growth=0.03,
                net_debt=0.0, shares_outstanding=10.0,
            )
        )


def test_growth_company_with_sourced_target_gets_orientation_not_94pct(engine):
    with Session(engine) as db:
        db.info["tenant_id"] = 2
        company = _company(db)
        InferredInputService().create(
            db, company, input_key="fcf_margin", value=Decimal("0.15"), base=BASE, source_urls=URLS
        )
        result = _value(db, company)
        assert result["status"] in ("ok", "partial")
        # Orientación, nunca valoración final.
        assert result["publishable"] is False
        assert "inferred_fcf_margin_target" in result["publication_blockers"]
        # Un valor positivo y razonable, no un -94 %: la quema actual converge
        # al margen objetivo en vez de proyectarse para siempre.
        assert result["base_value"] is not None and result["base_value"] > 0
        assert result["expected_value"] is not None and result["expected_value"] > 0
        trace = result["trace"]
        assert trace["method"] == "fcff_dcf_margin_convergence"
        assert trace["reported_fcf_margin"] == pytest.approx(-0.25)  # hecho medido
        assert trace["target_fcf_margin"] == pytest.approx(0.15)  # inferido marcado
        assert trace["target_fcf_margin_source_urls"] == URLS


def test_without_sourced_target_stays_explained_nd(engine):
    with Session(engine) as db:
        db.info["tenant_id"] = 2
        company = _company(db)
        result = _value(db, company)
        assert result["status"] == "insufficient_data"
        assert "non_negative_fcf_margin" in result["missing_inputs"]


def test_bear_scenario_nd_when_value_not_positive(engine):
    with Session(engine) as db:
        db.info["tenant_id"] = 2
        company = _company(db, "RKL2")
        InferredInputService().create(
            db, company, input_key="fcf_margin", value=Decimal("0.15"), base=BASE, source_urls=URLS
        )
        leveraged = {**VALUES, "net_debt": 50_000_000_000.0}  # deuda muy por encima del EV
        result = _value(db, company, values=leveraged)
        notes = result.get("scenario_notes") or {}
        assert notes.get("bear") or notes.get("expected")
        for name in ("bear", "base", "bull"):
            value = result[f"{name}_value"]
            assert value is None or value > 0  # nunca cifra negativa publicada
