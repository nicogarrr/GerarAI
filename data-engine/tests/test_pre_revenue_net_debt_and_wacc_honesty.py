"""El motor pre-revenue no inventa equity ni publica un WACC sin fuente.

Dos invariantes del paquete que este motor no cumplia:

1. ``net_debt`` ausente se coercía a 0.0 con ``or 0.0``. El puente de equity
   es EV - net_debt, así que un dato desconocido se convertía en "deuda cero":
   una biotech con EV 400M y 150M de caja no ingerida pasaba de 1,25 a
   2,00 EUR/acción sobre 200M de acciones (+60%) sin un solo fact detrás. El
   mismo ``or 0.0`` además borraba la diferencia entre un 0.0 legítimamente
   reportado y un dato ausente, y un NaN almacenado caía a 0.0 sin señal.

2. El WACC venía siempre de ``default_wacc`` (13% para tags speculative) sin
   ``CalculatedMetric`` que lo trazara, y aun así el resultado se publicaba
   como ``status="ok", publishable=True``. Con g terminal 2,5% el spread pasa
   de 6,0pp a 10,5pp: el factor de descuento del valor terminal cae de 1,80 a
   1,29 y el valor por acción se desploma ~-35% publicado como final.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import CalculatedMetric, Company, FinancialFact
from app.models.entities import Base
from app.valuation.engines.base import ValuationContext
from app.valuation.engines.pre_revenue import PreRevenueScenarioEngine
from app.valuation.financial_snapshot import FinancialSnapshot, FinancialSnapshotBuilder

PERIOD = "FY2025"
FY = 2025
SHARES = 200_000_000.0
# 150M de caja sin Facts de net_debt: el error del puente son exactamente
# 150M / 200M = 0,75 EUR/accion.
NET_CASH = 150_000_000.0
PRICE = 2.5


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.fixture
def company(db):
    row = Company(
        ticker="PRNET",
        name="Pre Revenue Net Debt Co",
        exchange="NASDAQ",
        currency="USD",
        sector="Health Care",
        industry="Biotechnology",
        company_type="biotech",
        valuation_model="pre_revenue",
        special_sources=[],
        special_risks=[],
        factor_tags=["pre_fcf", "speculative"],
    )
    db.add(row)
    db.flush()
    return row


def _fact(db, company, metric, value, *, unit="USD"):
    row = FinancialFact(
        company_id=company.id,
        metric=metric,
        value=Decimal(str(value)),
        unit=unit,
        period=PERIOD,
        fiscal_year=FY,
        fiscal_quarter="FY",
        source_type="contract_test",
        is_reported=True,
        confidence=Decimal("0.9"),
    )
    db.add(row)
    db.flush()
    return row


def _indicative_facts(db, company, *, net_debt=None):
    """Facts que dejan el snapshot incoherente y abren la rama indicativa.

    Falta el margen FCF normalizado (no hay ``fcf_margin`` ni
    ``free_cash_flow``) pero hay flujo de caja REPORTADO y positivo: asi el
    motor no necesita inferir nada y llega al rango indicativo sin consultas.
    """
    _fact(db, company, "revenue", 140_000_000.0)
    _fact(db, company, "shares_diluted", SHARES, unit="shares")
    _fact(db, company, "operating_cash_flow", 20_000_000.0)
    _fact(db, company, "cash_and_equivalents", NET_CASH)
    _fact(db, company, "capital_expenditure", -10_000_000.0)
    if net_debt is not None:
        _fact(db, company, "net_debt", net_debt)
    db.commit()


def _coherent_facts(db, company):
    _fact(db, company, "revenue", 140_000_000.0)
    _fact(db, company, "fcf_margin", 0.15)
    _fact(db, company, "revenue_growth", 0.05)
    _fact(db, company, "shares_diluted", SHARES, unit="shares")
    _fact(db, company, "net_debt", NET_CASH)
    _fact(db, company, "cash_and_equivalents", NET_CASH)
    _fact(db, company, "operating_cash_flow", 20_000_000.0)
    _fact(db, company, "capital_expenditure", -10_000_000.0)
    db.commit()


def _add_wacc_metric(db, company, value):
    db.add(
        CalculatedMetric(
            company_id=company.id,
            metric="wacc",
            value=Decimal(str(value)),
            unit="decimal",
            period=f"{FY}-12-31:FY",
            fiscal_year=FY,
            status="ok",
            definition_version="WACC_STANDARD_V1",
            formula="ke*E/(D+E) + kd*(1-t)*D/(D+E)",
        )
    )
    db.commit()


def _value(db, company, snapshot=None):
    return PreRevenueScenarioEngine().value(
        ValuationContext(
            db=db,
            company=company,
            snapshot=snapshot if snapshot is not None else FinancialSnapshotBuilder().build(db, company),
            current_price=PRICE,
            engine_key="pre_revenue",
        )
    )


# --------------------------------------------------------------------------
# net_debt ausente: se declara, no se convierte en deuda cero
# --------------------------------------------------------------------------


def test_missing_net_debt_is_declared_and_never_silently_zero(db, company):
    _indicative_facts(db, company)

    snapshot = FinancialSnapshotBuilder().build(db, company)
    assert snapshot.coherent is False
    result = _value(db, company, snapshot)

    # El dato que falta se nombra, tanto en missing_inputs como en los
    # publication blockers que consumen thesis y red team.
    assert "net_debt" in result["missing_inputs"]
    assert "net_debt" in result["publication_blockers"]
    assert result["publishable"] is False
    assert result["status"] == "partial"
    assert result["trace"]["net_debt"] is None
    assert result["trace"]["net_debt_source"] == "missing_assumed_zero"
    # El aviso deja claro que el numero por accion es EV/acciones, no equity.
    assert "EV/shares, not equity" in result["trace"]["notice"]
    assert "net_debt" in result["trace"]["publication_blockers"]
    # El aviso declara el margen realmente usado, no un 15% fijo.
    assumed = result["trace"]["assumed"]
    band = assumed["fcf_margin_band"]
    assert (
        f"base {assumed['fcf_margin_base']:.0%}, band {min(band):.0%}-{max(band):.0%}"
        in result["trace"]["notice"]
    )


def test_missing_net_debt_does_not_state_the_enterprise_value_as_equity(db, company):
    """El numero puede quedar como orientacion, pero no como valor de equity.

    Con 150M de caja sin ingestar, asumir deuda cero deja el equity 0,75
    EUR/accion por debajo del real: se comprueba que la diferencia entre el
    caso "sin dato" y el caso "con dato" es exactamente net_debt/shares.
    """
    _indicative_facts(db, company)
    without = _value(db, company)

    _fact(db, company, "net_debt", -NET_CASH)
    db.commit()
    with_cash = _value(db, company)

    assert "net_debt" not in with_cash["missing_inputs"]
    assert "net_debt" not in with_cash["publication_blockers"]
    assert with_cash["trace"]["net_debt"] == pytest.approx(-NET_CASH)
    assert with_cash["trace"]["net_debt_source"] == "financial_facts"
    # Equity = EV - net_debt, lineal en el dato.
    delta = with_cash["base_value"] - without["base_value"]
    assert delta == pytest.approx(NET_CASH / SHARES)
    # El error que se publicaba no era marginal: ~27% del valor de equity.
    assert without["base_value"] < with_cash["base_value"] * 0.8


def test_legitimate_zero_net_debt_is_traced_as_present_not_assumed(db, company):
    """`x or 0.0` no distingue un 0.0 reportado de un dato ausente."""
    _indicative_facts(db, company, net_debt=0.0)

    result = _value(db, company)

    assert result["trace"]["net_debt"] == pytest.approx(0.0)
    assert result["trace"]["net_debt_source"] == "financial_facts"
    assert "net_debt" not in result["missing_inputs"]
    assert "net_debt" not in result["publication_blockers"]


def test_coherent_snapshot_without_net_debt_refuses_to_value_equity(db, company):
    """Cierre defensivo del puente de equity (mismo criterio que standard_dcf)."""
    revenue = _fact(db, company, "revenue", 400_000_000.0)
    margin = _fact(db, company, "fcf_margin", 0.15)
    growth = _fact(db, company, "revenue_growth", 0.05)
    shares = _fact(db, company, "shares_diluted", SHARES, unit="shares")
    db.commit()

    snapshot = FinancialSnapshot(
        facts={
            "revenue": revenue,
            "fcf_margin": margin,
            "revenue_growth": growth,
            "shares_diluted": shares,
        },
        as_of_period=PERIOD,
        income_statement=PERIOD,
        shares_period=PERIOD,
        missing_inputs=[],
        coherent=True,
    )

    result = _value(db, company, snapshot)

    assert result["status"] == "insufficient_data"
    assert result["publishable"] is False
    assert result["missing_inputs"] == ["net_debt"]
    for field in ("bear_value", "base_value", "bull_value", "expected_value", "margin_of_safety"):
        assert result[field] is None, field


# --------------------------------------------------------------------------
# WACC sin CalculatedMetric: el rango se publica, no el veredicto
# --------------------------------------------------------------------------


def test_tag_default_wacc_blocks_publication_in_the_indicative_branch(db, company):
    _indicative_facts(db, company, net_debt=-NET_CASH)

    result = _value(db, company)

    assert result["trace"]["wacc"] == pytest.approx(0.13)
    assert result["trace"]["wacc_source"] == "tag_default"
    assert "traceable_wacc" in result["publication_blockers"]
    assert result["publishable"] is False
    assert result["status"] == "partial"
    assert "traceable_wacc" in result["trace"]["publication_blockers"]


def test_tag_default_wacc_is_not_published_as_a_final_valuation(db, company):
    _coherent_facts(db, company)

    result = _value(db, company)

    assert result["publication_blockers"] == ["traceable_wacc"]
    assert result["publishable"] is False
    assert result["status"] == "partial"
    assert result["trace"]["wacc_source"] == "tag_default"
    # Los numeros siguen, con su supuesto nombrado: una orientacion con las
    # hipotesis a la vista vale mas que un rechazo.
    assert result["expected_value"] is not None
    assert "not a dated source" in result["trace"]["notice"]


def test_traceable_wacc_is_used_and_unblocks_publication(db, company):
    _coherent_facts(db, company)
    tag_default = _value(db, company)

    _add_wacc_metric(db, company, 0.085)
    traceable = _value(db, company)

    assert traceable["publication_blockers"] == []
    assert traceable["publishable"] is True
    assert traceable["status"] == "ok"
    assert traceable["trace"]["wacc"] == pytest.approx(0.085)
    assert traceable["trace"]["wacc_source"] == "calculated_metric"
    # El 13% supuesto frente al 8,5% trazable es la diferencia entre publicar
    # un valor y publicar la mitad de ese valor.
    assert tag_default["base_value"] < traceable["base_value"] * 0.75