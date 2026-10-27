"""Bugs de dinero en el WACC y en el DCF.

Cada test fija un error concreto que hacia que el numero publicado no
correspondiera al modelo que el trace declaraba.

1. El peso de equity del WACC caia a `total_equity` (patrimonio contable)
   cuando no habia market cap. Book value mezclado con market value en el
   mismo peso.
2. `market_cap` (unidades absolutas de yfinance) y `total_debt` (magnitud
   dependiente de la fuente) se sumaban sin reconciliar. Con market cap real
   de 200M y debt de 300 (millones), el peso de deuda salia 1,5e-6 y el WACC
   18,0% donde correspondia 12,6%.
3. El motor pre-revenue clampeaba un margen de FCF negativo a +1%, convirtiendo
   una quema de caja en un FCF positivo.
"""

from decimal import Decimal

import pytest

from app.services.metric_calculation_service import (
    MetricCalculationService,
    _capital_scale_conflict,
)
from app.valuation.dcf_fcff import DCFInputs, run_dcf

PERIOD = "2025-12-31"


# --------------------------------------------------------------------------
# 1. El peso de equity debe ser valor de MERCADO
# --------------------------------------------------------------------------


def _wacc_facts(db, company, market_cap_source="test_wacc_units", total_debt_source="test_wacc_units", **overrides):
    base = {
        "risk_free_rate": "0.04",
        "beta": "1.0",
        "equity_risk_premium": "0.05",
        "country_risk_premium": "0.01",
        "interest_expense": "12",
        "total_debt": "300",
        "effective_tax_rate": "0.25",
    }
    base.update(overrides)
    for metric, value in base.items():
        if value is None:
            continue
        source = total_debt_source if metric == "total_debt" else (
            market_cap_source if metric in ("market_cap", "market_capitalization") else "test_wacc_units"
        )
        db.add(
            _fact(company, metric, value, PERIOD, 2025, None, source_type=source)
        )
    db.flush()


def _fact(company, metric, value, period, fiscal_year, fiscal_quarter, source_type="test_wacc_units"):
    from app.models import FinancialFact

    return FinancialFact(
        company_id=company.id,
        metric=metric,
        value=Decimal(value),
        unit="USD",
        period=period,
        fiscal_year=fiscal_year,
        fiscal_quarter=fiscal_quarter,
        source_type=source_type,
        is_reported=True,
        confidence=Decimal("0.90"),
    )


TEST_TICKER = "TWACC"


def _cleanup() -> None:
    from sqlalchemy import delete, select

    from app.core.database import SessionLocal, init_db
    from app.models import CalculatedMetric, Company, FinancialFact

    init_db()
    db = SessionLocal()
    try:
        for company in db.scalars(
            select(Company).where(Company.ticker == TEST_TICKER)
        ).all():
            db.execute(
                delete(CalculatedMetric).where(
                    CalculatedMetric.company_id == company.id
                )
            )
            db.execute(
                delete(FinancialFact).where(FinancialFact.company_id == company.id)
            )
            db.delete(company)
        db.commit()
    finally:
        db.close()


@pytest.fixture
def company_factory():
    from app.core.database import SessionLocal
    from tests.test_calculated_metrics import create_test_company

    _cleanup()
    db = SessionLocal()
    try:
        company = create_test_company(db, ticker=TEST_TICKER, name="WACC Units Co")
        yield db, company
        db.rollback()
    finally:
        db.close()
        _cleanup()


def test_wacc_never_uses_book_equity_as_market_equity(company_factory):
    """Sin market cap el WACC queda unavailable, no se sustituye por book value.

    Con market cap 10.000M, book equity 2.000M y debt 3.000M el WACC correcto
    es 7,08%; usando el patrimonio contable salia 5,60% (-21%). Como el DCF
    escala con 1/(WACC-g), eso es +48% de valor de salida.
    """
    db, company = company_factory
    _wacc_facts(db, company, total_debt="3000")
    db.add(_fact(company, "total_equity", "2000", PERIOD, 2025, None))
    db.commit()

    result = MetricCalculationService().calculate(db, company, "wacc", persist=False)

    assert result.status == "unavailable"
    assert "market_cap" in " ".join(result.calculation_trace.get("missing_inputs", []))
    # Y en ningún caso el valor publicado sale de un peso con book value.
    assert result.value is None


def test_wacc_uses_market_equity_when_available(company_factory):
    db, company = company_factory
    _wacc_facts(
        db,
        company,
        market_cap_source="yfinance",
        total_debt_source="SEC",
        market_cap="10000",
        total_debt="3000",
    )
    db.add(_fact(company, "total_equity", "2000", PERIOD, 2025, None))
    db.commit()

    result = MetricCalculationService().calculate(db, company, "wacc", persist=False)

    assert result.status == "ok"
    assert result.calculation_trace["equity_value_source"] == "market_cap"
    # E_w = 10000/13000, D_w = 3000/13000
    assert Decimal(result.calculation_trace["equity_weight"]) == Decimal(10000) / Decimal(
        13000
    )
    assert Decimal(result.calculation_trace["debt_weight"]) == Decimal(3000) / Decimal(
        13000
    )


def test_wacc_without_reported_debt_is_the_cost_of_equity_and_says_so(company_factory):
    """Deuda financiera reportada = 0: peso de deuda 0, sin coste de deuda inventado."""
    db, company = company_factory
    _wacc_facts(db, company, market_cap="10000", total_debt="0", interest_expense=None)
    db.commit()

    result = MetricCalculationService().calculate(db, company, "wacc", persist=False)

    assert result.status == "ok"
    trace = result.calculation_trace
    assert trace["cost_of_debt_source"] == "no_reported_debt"
    assert Decimal(trace["debt_weight"]) == 0
    # Ke = 4% + 1,0 x 5% + 1% = 10%
    assert result.value == Decimal("0.10000000")


def test_wacc_with_debt_but_no_interest_stays_unavailable(company_factory):
    db, company = company_factory
    _wacc_facts(db, company, market_cap="10000", total_debt="3000", interest_expense=None)
    db.commit()

    result = MetricCalculationService().calculate(db, company, "wacc", persist=False)

    assert result.status == "unavailable"
    assert "cost_of_debt_or_interest_expense" in result.calculation_trace["missing_inputs"]


# --------------------------------------------------------------------------
# 2. Escalas de importes incompatibles
# --------------------------------------------------------------------------


def _scale_fact(value, source_type, unit="USD"):
    from app.models import FinancialFact

    return FinancialFact(
        company_id=1,
        metric="m",
        value=Decimal(value),
        unit=unit,
        period=PERIOD,
        fiscal_year=2025,
        source_type=source_type,
        is_reported=True,
        confidence=Decimal("0.90"),
    )


@pytest.mark.parametrize(
    "equity,debt,equity_src,debt_src,expected",
    [
        # Ratios razonables: comparables vengan de donde vengan.
        ("10000", "3000", "yfinance", "SEC", False),
        # Falso positivo del detector por magnitud: mega-cap casi sin deuda
        # con AMBAS fuentes absolutas es estructura de capital real.
        ("200000000000", "300000000", "yfinance", "SEC", False),
        # Sin deuda: comparable con cualquier escala.
        ("10000", "0", "yfinance", "ESEF", False),
        # ESEF es fail-closed SIEMPRE: el pipeline pierde ix:nonFraction
        # scale, asi que ni mismo tipo+unidad ni magnitud razonable lo
        # verifican (dos documentos pueden escalar distinto: 666.667x).
        ("200000000", "300", "ESEF", "ESEF", True),
        ("200000000", "30000000", "ESEF", "ESEF", True),
        # Provenance mixta con ESEF: conflicto a cualquier magnitud
        # (el caso original: cap absoluto + debt escalado).
        ("200000000", "300", "yfinance", "ESEF", True),
        ("200000000", "30000000", "yfinance", "ESEF", True),
    ],
)
def test_capital_scale_guard(equity, debt, equity_src, debt_src, expected):
    assert (
        _capital_scale_conflict(
            _scale_fact(equity, equity_src), _scale_fact(debt, debt_src)
        )
        is expected
    )


def test_capital_scale_guard_fails_closed_on_currency_mismatch():
    """USD contra EUR no es un error de escala: es un error de divisa.

    Dos fuentes absolutas con unidades monetarias distintas no son
    comparables a ningun ratio: el WACC queda unavailable antes que
    sumar dolares con euros.
    """
    assert (
        _capital_scale_conflict(
            _scale_fact("10000", "yfinance", unit="USD"),
            _scale_fact("3000", "SEC", unit="EUR"),
        )
        is True
    )


def test_capital_scale_guard_fails_closed_on_uncertain_provenance():
    """Provenance no absoluta: la escala no se puede verificar.

    El atajo del ratio 100x dejaba pasar pares de procedencia incierta
    con magnitud razonable. Un ratio razonable no demuestra unidades
    compatibles: fail-closed a cualquier magnitud.
    """
    assert (
        _capital_scale_conflict(
            _scale_fact("10000", "manual"), _scale_fact("3000", "manual")
        )
        is True
    )
    assert (
        _capital_scale_conflict(
            _scale_fact("10000", "yfinance"), _scale_fact("3000", "manual")
        )
        is True
    )


def test_wacc_unavailable_when_capital_amounts_have_different_scales(company_factory):
    """market cap en unidades absolutas y debt en millones no son comparables.

    Con Ke 18% y Kd 9% el WACC correcto es 12,6%; sumando 300 contra
    2,0e8 salia 18,0% (+43%), y el valor de salida un -34%.
    """
    db, company = company_factory
    _wacc_facts(
        db,
        company,
        market_cap_source="yfinance",
        total_debt_source="ESEF",
        risk_free_rate="0.08",
        beta="1.5",
        market_cap="200000000",
        total_debt="300",
        interest_expense="27",
    )
    db.commit()

    result = MetricCalculationService().calculate(db, company, "wacc", persist=False)

    assert result.status == "unavailable"
    assert "capital_amounts_scale_mismatch" in " ".join(
        result.calculation_trace.get("missing_inputs", [])
    )


# --------------------------------------------------------------------------
# 3. El DCF no invierte el signo de una quema de caja
# --------------------------------------------------------------------------


def test_dcf_keeps_a_negative_fcf_margin_negative():
    result = run_dcf(
        DCFInputs(
            revenue=1000.0,
            revenue_growth=0.05,
            fcf_margin=-0.15,
            wacc=0.10,
            terminal_growth=0.03,
            net_debt=2000.0,
            shares_outstanding=100.0,
        )
    )
    assert all(row["fcf"] < 0 for row in result.forecast)
    assert result.enterprise_value < 0
    assert result.value_per_share < 0


def test_pre_revenue_engine_refuses_negative_per_share_value_on_cash_burn(company_factory):
    """Una quema de caja no publica un valor por accion negativo.

    Con margen reportado -15% el DCF FCFF da un valor por accion negativo
    (ASTS: -84,70 USD). El capital propio no vale menos de cero: el motor
    se niega (insufficient_data) en vez de publicar bear/base/bull negativos.
    """
    from app.valuation.engines.base import ValuationContext
    from app.valuation.engines.pre_revenue import PreRevenueScenarioEngine
    from app.valuation.financial_snapshot import FinancialSnapshotBuilder

    db, company = company_factory
    company.valuation_model = "pre_revenue"
    for metric, value in {
        "revenue": "1000",
        "shares_diluted": "100",
        "fcf_margin": "-0.15",
        "revenue_growth": "0.05",
        "net_debt": "2000",
    }.items():
        db.add(_fact(company, metric, value, PERIOD, 2025, None))
    db.commit()

    snapshot = FinancialSnapshotBuilder().build(db, company)
    assert snapshot.coherent
    result = PreRevenueScenarioEngine().value(
        ValuationContext(
            db=db,
            company=company,
            snapshot=snapshot,
            current_price=None,
            engine_key="pre_revenue",
        )
    )

    assert result["status"] == "insufficient_data"
    assert result["publishable"] is False
    assert "non_negative_fcf_margin" in result["missing_inputs"]
    for field in ("bear_value", "base_value", "bull_value", "expected_value"):
        assert result[field] is None, field


def test_dcf_reports_terminal_value_weight():
    result = run_dcf(
        DCFInputs(
            revenue=1000.0,
            revenue_growth=0.05,
            fcf_margin=0.20,
            wacc=0.10,
            terminal_growth=0.03,
            net_debt=0.0,
            shares_outstanding=100.0,
        )
    )
    share = result.trace["pv_terminal_share_of_ev"]
    assert 0.0 < share < 1.0
    assert result.trace["wacc_minus_growth"] == pytest.approx(0.07)


def test_dcf_rejects_a_wacc_below_minus_one():
    # (1 + wacc) ** year alternaria de signo y el valor presente seria
    # inventado.
    with pytest.raises(ValueError, match="greater than -1"):
        run_dcf(
            DCFInputs(
                revenue=1000.0,
                revenue_growth=0.0,
                fcf_margin=0.1,
                wacc=-1.5,
                terminal_growth=-2.0,
                net_debt=0.0,
                shares_outstanding=100.0,
            )
        )


def test_wacc_computes_for_megacap_with_tiny_real_debt(company_factory):
    """Regresion del falso positivo: ratio >100 con fuentes absolutas.

    market cap 200000M (yfinance, absoluto) y deuda 300M (SEC, absoluto)
    dan ratio ~667x: es una estructura de capital real, no un error de
    unidades, y el WACC debe calcularse.
    """
    db, company = company_factory
    _wacc_facts(
        db,
        company,
        market_cap_source="yfinance",
        total_debt_source="SEC",
        market_cap="200000000000",
        total_debt="300000000",
        interest_expense="27000000",
    )
    db.commit()

    result = MetricCalculationService().calculate(db, company, "wacc", persist=False)

    assert result.status == "ok"
    trace = result.calculation_trace
    assert Decimal(trace["debt_weight"]) == Decimal("300000000") / Decimal(
        "200300000000"
    )


def test_sotp_adr_does_not_invent_factor_eight_money_loss():
    from tests.test_sotp_engine import _sotp_result
    result = _sotp_result({}, tags=["sotp", "adr:8"], price=80)
    assert result["margin_of_safety"] == pytest.approx((result["expected_value"] - 10) / result["expected_value"])


def test_funding_gap_never_treats_missing_capex_or_ocf_as_zero_money():
    from app.valuation.funding_gap import estimate_funding_gap
    from tests.test_funding_gap import _snapshot_completo
    for absent in ("capital_expenditure", "operating_cash_flow"):
        result = estimate_funding_gap(_snapshot_completo(**{absent: None}), current_price=10, value_per_share=8)
        assert result.funding_gap is None
        assert result.dilution is None


def test_tax_rate_uses_latest_coherent_year_when_newest_pair_is_a_loss(company_factory):
    db, company = company_factory
    svc = MetricCalculationService()
    anchor = _fact(company, "risk_free_rate", "0.04", "2026-10-18", None, None)
    db.add(anchor)
    for metric, value, period, fy in (
        ("income_tax_expense", "10", "2025-12-31:FY", 2025),
        ("income_before_tax", "-50", "2025-12-31:FY", 2025),
        ("income_tax_expense", "20", "2024-12-31:FY", 2024),
        ("income_before_tax", "100", "2024-12-31:FY", 2024),
    ):
        db.add(_fact(company, metric, value, period, fy, None))
    db.flush()

    rate, trace, facts = svc._tax_rate_for_period(
        db, company, anchor, allow_fallback=False, allow_latest=True
    )

    assert rate == Decimal("0.2")
    assert trace["tax_rate_period"] == "2024-12-31:FY"
    assert trace["tax_rate_fallback"] is False
    assert set(facts) == {"income_tax_expense", "income_before_tax"}


def test_tax_rate_stays_missing_without_pretax_pair(company_factory):
    db, company = company_factory
    anchor = _fact(company, "risk_free_rate", "0.04", "2026-10-18", None, None)
    db.add(anchor)
    db.add(_fact(company, "income_tax_expense", "10", "2025-12-31:FY", 2025, None))
    db.flush()

    rate, trace, _ = MetricCalculationService()._tax_rate_for_period(
        db, company, anchor, allow_fallback=False, allow_latest=True
    )

    assert rate is None
    assert trace["tax_rate_source"] == "unavailable"
