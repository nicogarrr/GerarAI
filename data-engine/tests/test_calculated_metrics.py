from decimal import Decimal

from sqlalchemy import delete, select

import main
from app.core.database import SessionLocal, init_db
from app.models import CalculatedMetric, Company, FinancialFact
from app.services.metric_calculation_service import MetricCalculationService
from tests.auth_helpers import csrf_client

TEST_TICKER = "TCALC"
PEER_TICKERS = ["TPEER1", "TPEER2"]


def cleanup_metric_test_artifacts() -> None:
    init_db()
    db = SessionLocal()
    try:
        companies = db.scalars(select(Company).where(Company.ticker.in_([TEST_TICKER, *PEER_TICKERS]))).all()
        for company in companies:
            db.execute(delete(CalculatedMetric).where(CalculatedMetric.company_id == company.id))
            db.execute(delete(FinancialFact).where(FinancialFact.company_id == company.id))
            db.delete(company)
        db.commit()
    finally:
        db.close()


def create_test_company(db, ticker: str = TEST_TICKER, name: str = "Traceable Metrics Test Co") -> Company:
    company = Company(
        ticker=ticker,
        name=name,
        exchange="TEST",
        currency="USD",
        sector="Software",
        industry="Application Software",
        company_type="standard",
        valuation_model="standard_dcf",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.flush()
    return company


def add_fact(
    db,
    company: Company,
    metric: str,
    value: str,
    period: str = "FY2025",
    fiscal_year: int = 2025,
    fiscal_quarter: str | None = "FY",
    is_reported: bool = True,
    source_type: str = "test_metric",
) -> FinancialFact:
    fact = FinancialFact(
        company_id=company.id,
        metric=metric,
        value=Decimal(value),
        unit="USD" if metric != "shares_diluted" else "shares",
        period=period,
        fiscal_year=fiscal_year,
        fiscal_quarter=fiscal_quarter,
        source_type=source_type,
        is_reported=is_reported,
        confidence=Decimal("0.90"),
    )
    db.add(fact)
    return fact


def test_calculated_metrics_are_persisted_with_trace():
    cleanup_metric_test_artifacts()
    db = SessionLocal()
    try:
        company = create_test_company(db)
        add_fact(db, company, "revenue", "1000")
        add_fact(db, company, "free_cash_flow", "250")
        add_fact(db, company, "net_income", "180")
        add_fact(db, company, "operating_income", "250")
        add_fact(db, company, "gross_profit", "650")
        add_fact(db, company, "total_equity", "800")
        add_fact(db, company, "total_assets", "1500")
        add_fact(db, company, "total_debt", "200")
        add_fact(db, company, "cash_and_equivalents", "100")
        add_fact(db, company, "ebitda", "300")
        db.commit()
    finally:
        db.close()

    client = csrf_client(main.app)
    response = client.post(f"/api/companies/{TEST_TICKER}/metrics/refresh")
    assert response.status_code == 200
    payload = response.json()
    metrics = {item["metric"]: item for item in payload["metrics"]}

    assert metrics["fcf_margin"]["status"] == "ok"
    assert Decimal(metrics["fcf_margin"]["value"]) == Decimal("0.25000000")
    assert metrics["fcf_margin"]["formula"] == "free_cash_flow / revenue"
    assert metrics["fcf_margin"]["numerator"] == "250.00000000"
    assert metrics["fcf_margin"]["denominator"] == "1000.00000000"
    assert len(metrics["fcf_margin"]["source_fact_ids"]) == 2
    assert metrics["fcf_margin"]["calculation_trace"]["method"] == "simple_ratio"

    assert metrics["roic"]["status"] == "ok"
    assert Decimal(metrics["roic"]["value"]) == Decimal("0.21944444")
    assert metrics["roic"]["definition_version"] == "ROIC_STANDARD_V2"
    assert metrics["roic"]["calculation_trace"]["method"] == "standard_roic"
    assert metrics["roic"]["calculation_trace"]["tax_rate_source"] == "statutory_fallback"
    assert metrics["roic"]["calculation_trace"]["tax_rate_fallback_reason"]

    db = SessionLocal()
    try:
        stored = db.scalar(
            select(CalculatedMetric).where(
                CalculatedMetric.metric == "fcf_margin",
                CalculatedMetric.period == "FY2025",
            )
        )
        assert stored is not None
        assert stored.definition_version == "FCF_MARGIN_V1"
        assert stored.source_fact_ids
    finally:
        db.close()
        cleanup_metric_test_artifacts()


def test_calculated_metrics_report_unavailable_when_inputs_are_missing():
    cleanup_metric_test_artifacts()
    db = SessionLocal()
    try:
        company = create_test_company(db)
        add_fact(db, company, "revenue", "1000")
        db.commit()
    finally:
        db.close()

    client = csrf_client(main.app)
    response = client.post(f"/api/companies/{TEST_TICKER}/metrics/refresh")
    assert response.status_code == 200
    metrics = {item["metric"]: item for item in response.json()["metrics"]}

    assert metrics["fcf_margin"]["status"] == "unavailable"
    assert metrics["fcf_margin"]["value"] is None
    assert "free_cash_flow" in metrics["fcf_margin"]["calculation_trace"]["missing_inputs"]

    cleanup_metric_test_artifacts()


def test_roic_v2_uses_reported_tax_and_average_invested_capital():
    cleanup_metric_test_artifacts()
    db = SessionLocal()
    try:
        company = create_test_company(db)
        add_fact(db, company, "operating_income", "200")
        add_fact(db, company, "total_debt", "300")
        add_fact(db, company, "total_equity", "700")
        add_fact(db, company, "cash_and_equivalents", "100")
        add_fact(db, company, "income_tax_expense", "50")
        add_fact(db, company, "income_before_tax", "200")
        add_fact(db, company, "total_debt", "200", "FY2024", 2024)
        add_fact(db, company, "total_equity", "600", "FY2024", 2024)
        add_fact(db, company, "cash_and_equivalents", "100", "FY2024", 2024)
        db.commit()

        result = MetricCalculationService().calculate(
            db,
            company,
            "roic",
            persist=True,
        )
        db.commit()

        assert result.status == "ok"
        assert result.definition_version == "ROIC_STANDARD_V2"
        assert result.value == Decimal("0.18750000")
        assert result.numerator == Decimal("150.00000000")
        assert result.denominator == Decimal("800.00000000")
        assert result.calculation_trace["tax_rate_source"] == "reported_income_statement"
        assert Decimal(result.calculation_trace["tax_rate"]) == Decimal("0.25")
        assert (
            result.calculation_trace["invested_capital_basis"]
            == "average_current_and_prior_period"
        )
        assert result.calculation_trace["prior_invested_capital"] == "700.000000"
        assert len(result.source_fact_ids) == 9

        stored = db.scalar(
            select(CalculatedMetric).where(
                CalculatedMetric.company_id == company.id,
                CalculatedMetric.metric == "roic",
                CalculatedMetric.definition_version == "ROIC_STANDARD_V2",
            )
        )
        assert stored is not None
        assert stored.value == Decimal("0.18750000")
    finally:
        db.close()
        cleanup_metric_test_artifacts()


def test_adjusted_roic_requires_and_traces_all_capital_adjustments():
    cleanup_metric_test_artifacts()
    db = SessionLocal()
    try:
        company = create_test_company(db)
        add_fact(db, company, "operating_income", "200")
        add_fact(db, company, "total_debt", "300")
        add_fact(db, company, "total_equity", "700")
        add_fact(db, company, "cash_and_equivalents", "100")
        add_fact(db, company, "goodwill", "150")
        add_fact(db, company, "intangible_assets", "50")
        add_fact(db, company, "effective_tax_rate", "0.25")
        db.commit()

        service = MetricCalculationService()
        unavailable = service.calculate(
            db,
            company,
            "roic_adjusted",
            persist=False,
        )
        assert unavailable.status == "unavailable"
        assert (
            "operating_lease_liabilities"
            in unavailable.calculation_trace["missing_inputs"]
        )

        add_fact(db, company, "operating_lease_liabilities", "100")
        db.commit()
        result = service.calculate(db, company, "roic_adjusted", persist=True)
        db.commit()

        assert result.status == "ok"
        assert result.definition_version == "ROIC_ADJUSTED_V1"
        assert result.value == Decimal("0.18750000")
        assert result.denominator == Decimal("800.00000000")
        assert result.calculation_trace["method"] == "adjusted_roic"
        assert result.calculation_trace["adjustments"] == {
            "goodwill_removed": "150.000000",
            "intangible_assets_removed": "50.000000",
            "operating_lease_liabilities_added": "100.000000",
            "numerator_adjustments": (
                "none; no amortization or lease-interest add-back is made "
                "without separately reported inputs"
            ),
        }
        assert len(result.source_fact_ids) == 8
    finally:
        db.close()
        cleanup_metric_test_artifacts()


def test_wacc_v1_traces_derived_debt_cost_country_risk_currency_and_date():
    cleanup_metric_test_artifacts()
    db = SessionLocal()
    try:
        company = create_test_company(db)
        period = "2025-12-31"
        add_fact(db, company, "risk_free_rate", "0.04", period, 2025, None)
        add_fact(db, company, "beta", "1.2", period, 2025, None)
        add_fact(db, company, "equity_risk_premium", "0.05", period, 2025, None)
        add_fact(db, company, "country_risk_premium", "0.01", period, 2025, None)
        # Fuentes absolutas y misma unidad: el guard de capital es
        # fail-closed con provenance incierta (#375).
        add_fact(db, company, "market_cap", "800", period, 2025, None, source_type="yfinance")
        add_fact(db, company, "interest_expense", "12")
        add_fact(db, company, "total_debt", "200", source_type="SEC")
        add_fact(db, company, "effective_tax_rate", "0.25")
        db.commit()

        result = MetricCalculationService().calculate(
            db,
            company,
            "wacc",
            persist=True,
        )
        db.commit()

        assert result.status == "ok"
        assert result.definition_version == "WACC_STANDARD_V1"
        assert result.value == Decimal("0.09700000")
        assert result.calculation_trace["cost_of_debt_source"] == (
            "interest_expense_over_debt"
        )
        assert result.calculation_trace["cost_of_debt"] == "0.06"
        assert result.calculation_trace["country_risk_premium"] == "0.010000"
        assert result.calculation_trace["currency"] == "USD"
        assert result.calculation_trace["as_of_date"] == "2025-12-31"
        assert result.calculation_trace["equity_value_source"] == "market_cap"
        assert result.calculation_trace["input_period_alignment"] == (
            "mixed_latest_available"
        )
        assert len(result.source_fact_ids) == 8

        add_fact(db, company, "cost_of_debt", "0.06")
        db.commit()
        direct_cost_result = MetricCalculationService().calculate(
            db,
            company,
            "wacc",
            persist=False,
        )
        assert direct_cost_result.value == Decimal("0.09700000")
        assert direct_cost_result.calculation_trace["cost_of_debt_source"] == (
            "reported_cost_of_debt"
        )
    finally:
        db.close()
        cleanup_metric_test_artifacts()


def test_cfroi_v1_is_persisted_unavailable_and_never_proxied():
    cleanup_metric_test_artifacts()
    db = SessionLocal()
    try:
        company = create_test_company(db)
        db.commit()

        result = MetricCalculationService().calculate(
            db,
            company,
            "cfroi",
            persist=True,
        )
        db.commit()

        assert result.status == "unavailable"
        assert result.value is None
        assert result.definition_version == "CFROI_V1"
        assert result.calculation_trace["reason"] == (
            "specialized_methodology_inputs_required"
        )
        assert result.calculation_trace["required_inputs"]
        assert result.calculation_trace["policy"] == (
            "persist_unavailable_never_fabricate"
        )

        stored = db.scalar(
            select(CalculatedMetric).where(
                CalculatedMetric.company_id == company.id,
                CalculatedMetric.metric == "cfroi",
                CalculatedMetric.definition_version == "CFROI_V1",
            )
        )
        assert stored is not None
        assert stored.status == "unavailable"
        assert stored.value is None
    finally:
        db.close()
        cleanup_metric_test_artifacts()


def test_peer_comparison_uses_traceable_metrics_and_multifactor_peers():
    cleanup_metric_test_artifacts()
    db = SessionLocal()
    try:
        target = create_test_company(db)
        peer_1 = create_test_company(db, "TPEER1", "Traceable Peer One")
        peer_2 = create_test_company(db, "TPEER2", "Traceable Peer Two")

        for company, revenue, fcf, net_income, operating_income, gross_profit in [
            (target, "1000", "250", "180", "250", "650"),
            (peer_1, "1000", "100", "120", "180", "500"),
            (peer_2, "1000", "300", "220", "280", "700"),
        ]:
            add_fact(db, company, "revenue", revenue)
            add_fact(db, company, "free_cash_flow", fcf)
            add_fact(db, company, "net_income", net_income)
            add_fact(db, company, "operating_income", operating_income)
            add_fact(db, company, "gross_profit", gross_profit)
        db.commit()
    finally:
        db.close()

    client = csrf_client(main.app)
    response = client.get(f"/api/companies/{TEST_TICKER}/peers/comparison?metrics=fcf_margin,net_margin&limit=2")
    assert response.status_code == 200
    payload = response.json()

    assert payload["ticker"] == TEST_TICKER
    assert payload["basis"] == "multifactor_business_model_stage_size"
    assert payload["selection_trace"]["method"] == "PEER_SELECTION_V2"
    selected_candidates = {
        candidate["ticker"]: candidate
        for candidate in payload["selection_trace"]["candidates"]
        if candidate["selected"]
    }
    assert set(selected_candidates) == set(PEER_TICKERS)
    assert all(
        candidate["dimensions"]["industry"] == 1.0
        and "same industry" in candidate["rationale"]
        for candidate in selected_candidates.values()
    )
    assert payload["peer_count"] == 2
    assert payload["companies"][0]["is_target"] is True
    assert payload["companies"][0]["metrics"]["fcf_margin"]["source_fact_ids"]
    # F26: con 2 comparables con dato (n<3) no hay mediana; el target sigue visible.
    fcf = payload["benchmarks"]["fcf_margin"]
    assert fcf["peer_median"] is None and fcf["peer_average"] is None
    assert fcf["insufficient_sample"] is True
    assert fcf["note"] == "muestra insuficiente (n<3)"
    assert fcf["target_vs_peer_median"] is None
    assert Decimal(fcf["target_value"]) == Decimal("0.25000000")
    assert payload["peer_count"] == 2 and payload["peers_without_data"] == []

    cleanup_metric_test_artifacts()


def add_quality_year_facts(db, company: Company, years: list[int]) -> None:
    for year in years:
        period = f"FY{year}"
        add_fact(db, company, "revenue", "1000", period, year)
        add_fact(db, company, "free_cash_flow", "100", period, year)
        add_fact(db, company, "net_income", "200", period, year)
        add_fact(db, company, "total_equity", "1000", period, year)
        add_fact(db, company, "total_assets", "2000", period, year)


def test_windowed_ratio_requires_minimum_history():
    cleanup_metric_test_artifacts()
    db = SessionLocal()
    try:
        company = create_test_company(db)
        add_quality_year_facts(db, company, [2024, 2025])
        db.commit()

        result = MetricCalculationService().calculate(
            db, company, "fcf_margin_5y", persist=True
        )
        assert result.status == "unavailable"
        assert result.calculation_trace["reason"] == "insufficient_history"
        assert result.calculation_trace["coverage"] == "2/5"
        assert result.value is None
    finally:
        db.close()
        cleanup_metric_test_artifacts()


def test_windowed_ratio_averages_five_years_with_coverage():
    cleanup_metric_test_artifacts()
    db = SessionLocal()
    try:
        company = create_test_company(db)
        add_quality_year_facts(db, company, [2021, 2022, 2023, 2024, 2025])
        db.commit()

        result = MetricCalculationService().calculate(
            db, company, "fcf_margin_5y", persist=True
        )
        assert result.status == "ok"
        assert result.definition_version == "FCF_MARGIN_5Y_V1"
        assert result.value == Decimal("0.10000000")
        assert result.period == "FY2021-FY2025"
        assert result.calculation_trace["coverage"] == "5/5"
        assert result.calculation_trace["years"] == [2021, 2022, 2023, 2024, 2025]
        assert result.calculation_trace["aggregation"] == "mean_of_annual_ratios"

        stored = db.scalar(
            select(CalculatedMetric).where(
                CalculatedMetric.company_id == company.id,
                CalculatedMetric.metric == "fcf_margin_5y",
            )
        )
        assert stored is not None
        assert stored.value == Decimal("0.10000000")
    finally:
        db.close()
        cleanup_metric_test_artifacts()


def test_windowed_ratio_real_period_row_replaces_unknown_period_row():
    cleanup_metric_test_artifacts()
    db = SessionLocal()
    try:
        company = create_test_company(db)
        add_quality_year_facts(db, company, [2024, 2025])
        db.commit()

        service = MetricCalculationService()
        first = service.calculate(db, company, "fcf_margin_5y", persist=True)
        assert first.status == "unavailable"
        assert first.period == "FY2024-FY2025"

        add_quality_year_facts(db, company, [2021, 2022, 2023])
        db.commit()
        second = service.calculate(db, company, "fcf_margin_5y", persist=True)
        assert second.status == "ok"
        assert second.period == "FY2021-FY2025"

        periods = db.scalars(
            select(CalculatedMetric.period).where(
                CalculatedMetric.company_id == company.id,
                CalculatedMetric.metric == "fcf_margin_5y",
            )
        ).all()
        assert periods == ["FY2021-FY2025"]
    finally:
        db.close()
        cleanup_metric_test_artifacts()


def test_quality_moat_score_full_pass_and_partial_coverage():
    cleanup_metric_test_artifacts()
    db = SessionLocal()
    try:
        company = create_test_company(db)
        add_quality_year_facts(db, company, [2021, 2022, 2023, 2024, 2025])
        add_fact(db, company, "operating_income", "300", "FY2025", 2025)
        add_fact(db, company, "total_debt", "500", "FY2025", 2025, source_type="SEC")
        add_fact(db, company, "cash_and_equivalents", "100", "FY2025", 2025)
        add_fact(db, company, "income_tax_expense", "75", "FY2025", 2025)
        add_fact(db, company, "income_before_tax", "300", "FY2025", 2025)
        db.commit()

        service = MetricCalculationService()

        partial = service.calculate(db, company, "quality_moat_score", persist=True)
        db.commit()
        assert partial.status == "partial"
        assert partial.value == Decimal("4")
        checks = {c["check"]: c for c in partial.calculation_trace["checks"]}
        assert checks["fcf_margin_5y_gt_5pct"]["passed"] is True
        assert checks["net_margin_5y_gt_15pct"]["passed"] is True
        assert checks["roe_5y_gt_15pct"]["passed"] is True
        assert checks["roa_5y_gt_7pct"]["passed"] is True
        assert checks["roic_gt_wacc"]["passed"] is None
        assert partial.calculation_trace["checks_evaluable"] == 4

        add_fact(db, company, "risk_free_rate", "0.04", "2025-12-31", 2025, None)
        add_fact(db, company, "beta", "1.2", "2025-12-31", 2025, None)
        add_fact(db, company, "equity_risk_premium", "0.05", "2025-12-31", 2025, None)
        add_fact(db, company, "country_risk_premium", "0.01", "2025-12-31", 2025, None)
        add_fact(db, company, "market_cap", "2000", "2025-12-31", 2025, None, source_type="yfinance")
        add_fact(db, company, "interest_expense", "30", "FY2025", 2025)
        add_fact(db, company, "effective_tax_rate", "0.25", "FY2025", 2025)
        db.commit()

        full = service.calculate(db, company, "quality_moat_score", persist=True)
        db.commit()
        assert full.status == "ok"
        assert full.value == Decimal("5")
        full_checks = {c["check"]: c for c in full.calculation_trace["checks"]}
        assert full_checks["roic_gt_wacc"]["passed"] is True
        assert full.calculation_trace["checks_evaluable"] == 5
        assert full.definition_version == "MARCO_V1"
    finally:
        db.close()
        cleanup_metric_test_artifacts()


def test_owner_earnings_declared_maintenance_capex_rule():
    cleanup_metric_test_artifacts()
    db = SessionLocal()
    try:
        company = create_test_company(db)
        add_fact(db, company, "net_income", "200")
        add_fact(db, company, "depreciation_amortization", "80")
        add_fact(db, company, "capital_expenditure", "-120")
        # signo de flujo de caja: -30 = el circulante absorbio 30 de caja
        add_fact(db, company, "change_in_working_capital", "-30")
        db.commit()

        service = MetricCalculationService()
        result = service.calculate(db, company, "owner_earnings", persist=True)
        db.commit()
        assert result.status == "ok"
        assert result.definition_version == "OWNER_EARNINGS_V2"
        # maintenance = min(120, 80) = 80 -> 200 + 80 + (-30) - 80 = 170
        assert result.value == Decimal("170.00000000")
        assert result.calculation_trace["change_in_working_capital"] == "-30.00000000"
        assert result.calculation_trace["maintenance_capex"] == "80.00000000"
        assert result.calculation_trace["estimated_growth_capex"] == "40.00000000"

        # capex por debajo de D&A: maintenance = capex entero
        db.execute(
            delete(FinancialFact).where(
                FinancialFact.company_id == company.id,
                FinancialFact.metric == "capital_expenditure",
            )
        )
        add_fact(db, company, "capital_expenditure", "-50")
        db.commit()
        result2 = service.calculate(db, company, "owner_earnings", persist=False)
        # 200 + 80 + (-30) - 50 = 200
        assert result2.value == Decimal("200.00000000")
        assert result2.calculation_trace["maintenance_capex"] == "50.00000000"

        # sin variacion del circulante: unavailable, nunca se toma como 0
        db.execute(
            delete(FinancialFact).where(
                FinancialFact.company_id == company.id,
                FinancialFact.metric == "change_in_working_capital",
            )
        )
        db.commit()
        no_wc = service.calculate(db, company, "owner_earnings", persist=False)
        assert no_wc.status == "unavailable"
        assert "change_in_working_capital" in no_wc.calculation_trace["missing_inputs"]
        add_fact(db, company, "change_in_working_capital", "-30")
        db.commit()

        # sin D&A: unavailable honesto, nunca estimado
        db.execute(
            delete(FinancialFact).where(
                FinancialFact.company_id == company.id,
                FinancialFact.metric == "depreciation_amortization",
            )
        )
        db.commit()
        unavailable = service.calculate(db, company, "owner_earnings", persist=False)
        assert unavailable.status == "unavailable"
        assert "depreciation_amortization" in unavailable.calculation_trace["missing_inputs"]
    finally:
        db.close()
        cleanup_metric_test_artifacts()


def test_cfroi_approx_is_declared_and_never_confused_with_cfroi_v1():
    cleanup_metric_test_artifacts()
    db = SessionLocal()
    try:
        company = create_test_company(db)
        add_fact(db, company, "net_income", "200")
        add_fact(db, company, "depreciation_amortization", "80")
        add_fact(db, company, "interest_expense", "50")
        add_fact(db, company, "total_assets", "2000")
        add_fact(db, company, "income_tax_expense", "75")
        add_fact(db, company, "income_before_tax", "300")
        db.commit()

        result = MetricCalculationService().calculate(db, company, "cfroi_approx", persist=True)
        db.commit()
        assert result.status == "ok"
        assert result.definition_version == "CFROI_APPROX_V1"
        # (200 + 80 + 50*0.75) / 2000 = 317.5 / 2000
        assert result.value == Decimal("0.15875000")
        assert "approximation" in result.calculation_trace
        assert result.calculation_trace["tax_rate_source"] == "reported_income_statement"

        # CFROI_V1 real sigue negandose a estimar (sin inputs de inversion bruta)
        real = MetricCalculationService().calculate(db, company, "cfroi", persist=False)
        assert real.status == "unavailable"
    finally:
        db.close()
        cleanup_metric_test_artifacts()


def add_owner_year_facts(db, company: Company, years: list[int], capex: str = "-80") -> None:
    for year in years:
        period = f"FY{year}"
        add_fact(db, company, "depreciation_amortization", "100", period, year)
        add_fact(db, company, "capital_expenditure", capex, period, year)
        # signo de flujo de caja: -20 = el circulante absorbio 20 de caja
        add_fact(db, company, "change_in_working_capital", "-20", period, year)


def add_wacc_facts(db, company: Company) -> None:
    add_fact(db, company, "risk_free_rate", "0.04", "2025-12-31", 2025, None)
    add_fact(db, company, "beta", "1.2", "2025-12-31", 2025, None)
    add_fact(db, company, "equity_risk_premium", "0.05", "2025-12-31", 2025, None)
    add_fact(db, company, "country_risk_premium", "0.01", "2025-12-31", 2025, None)
    add_fact(db, company, "market_cap", "2000", "2025-12-31", 2025, None, source_type="yfinance")
    add_fact(db, company, "interest_expense", "30", "FY2025", 2025)
    add_fact(db, company, "effective_tax_rate", "0.25", "FY2025", 2025)


def test_owner_earnings_5y_mean_of_annual_values():
    cleanup_metric_test_artifacts()
    db = SessionLocal()
    try:
        company = create_test_company(db)
        add_quality_year_facts(db, company, [2021, 2022, 2023, 2024, 2025])
        add_owner_year_facts(db, company, [2021, 2022, 2023, 2024, 2025])
        db.commit()

        result = MetricCalculationService().calculate(db, company, "owner_earnings_5y", persist=True)
        assert result.status == "ok"
        assert result.definition_version == "OWNER_EARNINGS_5Y_V2"
        # 200 NI + 100 D&A + (-20) dCC - min(80, 100) = 200 cada ano
        assert result.value == Decimal("200.00000000")
        assert result.period == "FY2021-FY2025"
        assert result.calculation_trace["coverage"] == "5/5"
    finally:
        db.close()
        cleanup_metric_test_artifacts()


def test_owner_earnings_5y_requires_minimum_history():
    cleanup_metric_test_artifacts()
    db = SessionLocal()
    try:
        company = create_test_company(db)
        add_quality_year_facts(db, company, [2024, 2025])
        add_owner_year_facts(db, company, [2024, 2025])
        db.commit()

        result = MetricCalculationService().calculate(db, company, "owner_earnings_5y", persist=True)
        assert result.status == "unavailable"
        assert result.calculation_trace["reason"] == "insufficient_history"
    finally:
        db.close()
        cleanup_metric_test_artifacts()


def test_capex_to_da_5y_uses_absolute_capex():
    cleanup_metric_test_artifacts()
    db = SessionLocal()
    try:
        company = create_test_company(db)
        add_quality_year_facts(db, company, [2021, 2022, 2023, 2024, 2025])
        add_owner_year_facts(db, company, [2021, 2022, 2023, 2024, 2025], capex="-150")
        db.commit()

        result = MetricCalculationService().calculate(db, company, "capex_to_da_5y", persist=True)
        assert result.status == "ok"
        assert result.definition_version == "CAPEX_TO_DA_5Y_V1"
        assert result.value == Decimal("1.50000000")
    finally:
        db.close()
        cleanup_metric_test_artifacts()


def test_early_stage_moat_quality_is_not_spurious_zero_of_eight():
    cleanup_metric_test_artifacts()
    db = SessionLocal()
    try:
        company = create_test_company(db)
        company.company_type = "space_telecom_pre_fcf"
        company.factor_tags = ["space", "pre_fcf"]
        for year in [2021, 2022, 2023, 2024, 2025]:
            add_fact(db, company, "revenue", "4400000", f"FY{year}", year)
            add_fact(db, company, "net_income", "-50000000", f"FY{year}", year)
            add_fact(db, company, "free_cash_flow", "-80000000", f"FY{year}", year)
            add_fact(db, company, "total_assets", "100000000", f"FY{year}", year)
            add_fact(db, company, "total_equity", "100000000", f"FY{year}", year)
        db.commit()
        result = MetricCalculationService().calculate(db, company, "quality_moat_score_v2", persist=True)
        assert result.status == "unavailable"
        assert result.value is None
        assert result.calculation_trace["profile"] == "early_stage"
        assert result.calculation_trace["checks_evaluable"] == 0
        assert result.calculation_trace["score_comparable"] is False
        assert all(check["passed"] is None for check in result.calculation_trace["checks"])
        assert any(check["value"] is not None for check in result.calculation_trace["checks"])
        db.commit()
        stored = db.scalar(select(CalculatedMetric).where(
            CalculatedMetric.company_id == company.id,
            CalculatedMetric.metric == "quality_moat_score_v2",
        ))
        assert stored.calculation_trace["profile"] == "early_stage"
    finally:
        db.close()
        cleanup_metric_test_artifacts()


def test_quality_profile_transition_updates_persisted_trace_same_period():
    """Regression: mature -> pre-FCF must replace JSON trace on an existing row."""
    cleanup_metric_test_artifacts()
    db = SessionLocal()
    try:
        company = create_test_company(db)
        add_quality_year_facts(db, company, [2021, 2022, 2023, 2024, 2025])
        db.commit()
        service = MetricCalculationService()
        mature = service.calculate(db, company, "quality_moat_score_v2", persist=True)
        assert mature.calculation_trace["profile"] == "mature"
        assert mature.calculation_trace["score_comparable"] is True
        mature_id = mature.id
        mature_period = mature.period
        db.commit()
        db.expire_all()

        company = db.get(Company, company.id)
        company.company_type = "space_telecom_pre_fcf"
        company.factor_tags = ["space", "pre_fcf"]
        updated = service.calculate(db, company, "quality_moat_score_v2", persist=True)
        assert updated.id == mature_id
        assert updated.period == mature_period
        assert updated.status == "unavailable"
        assert updated.calculation_trace["score_comparable"] is False
        db.commit()
        db.expunge_all()

        stored = db.get(CalculatedMetric, mature_id)
        assert stored is not None
        assert stored.period == mature_period
        assert stored.status == "unavailable"
        assert stored.calculation_trace["profile"] == "early_stage"
        assert stored.calculation_trace["score_comparable"] is False
        assert stored.calculation_trace["checks_evaluable"] == 0
        assert all(c["passed"] is None for c in stored.calculation_trace["checks"])
    finally:
        db.close()
        cleanup_metric_test_artifacts()


def test_quality_moat_score_v2_full_pass_and_partial():
    cleanup_metric_test_artifacts()
    db = SessionLocal()
    try:
        company = create_test_company(db)
        add_quality_year_facts(db, company, [2021, 2022, 2023, 2024, 2025])
        add_owner_year_facts(db, company, [2021, 2022, 2023, 2024, 2025])
        add_fact(db, company, "operating_income", "300", "FY2025", 2025)
        add_fact(db, company, "total_debt", "500", "FY2025", 2025, source_type="SEC")
        add_fact(db, company, "cash_and_equivalents", "100", "FY2025", 2025)
        add_fact(db, company, "income_tax_expense", "75", "FY2025", 2025)
        add_fact(db, company, "income_before_tax", "300", "FY2025", 2025)
        db.commit()

        service = MetricCalculationService()

        partial = service.calculate(db, company, "quality_moat_score_v2", persist=True)
        db.commit()
        assert partial.status == "partial"
        assert partial.definition_version == "MARCO_V2"
        checks = {c["check"]: c for c in partial.calculation_trace["checks"]}
        assert len(checks) == 8
        assert checks["owner_earnings_5y_positive"]["passed"] is True
        assert checks["capex_to_da_5y_le_150pct"]["passed"] is True
        assert checks["roic_gt_wacc"]["passed"] is None
        assert checks["cfroi_approx_gt_wacc"]["passed"] is None
        assert partial.value == Decimal("6")

        add_wacc_facts(db, company)
        db.commit()

        full = service.calculate(db, company, "quality_moat_score_v2", persist=True)
        db.commit()
        assert full.status == "ok"
        assert full.value == Decimal("8")
        full_checks = {c["check"]: c for c in full.calculation_trace["checks"]}
        assert full_checks["cfroi_approx_gt_wacc"]["passed"] is True
        assert full_checks["roic_gt_wacc"]["passed"] is True
        assert full.calculation_trace["checks_evaluable"] == 8
    finally:
        db.close()
        cleanup_metric_test_artifacts()


def test_quality_moat_score_v2_capex_intensity_fails_when_heavy():
    cleanup_metric_test_artifacts()
    db = SessionLocal()
    try:
        company = create_test_company(db)
        add_quality_year_facts(db, company, [2021, 2022, 2023, 2024, 2025])
        add_owner_year_facts(db, company, [2021, 2022, 2023, 2024, 2025], capex="-300")
        add_fact(db, company, "operating_income", "300", "FY2025", 2025)
        add_fact(db, company, "total_debt", "500", "FY2025", 2025, source_type="SEC")
        add_fact(db, company, "cash_and_equivalents", "100", "FY2025", 2025)
        add_fact(db, company, "income_tax_expense", "75", "FY2025", 2025)
        add_fact(db, company, "income_before_tax", "300", "FY2025", 2025)
        db.commit()

        result = MetricCalculationService().calculate(db, company, "quality_moat_score_v2", persist=True)
        checks = {c["check"]: c for c in result.calculation_trace["checks"]}
        # |capex|/D&A = 3.0 > 1.5: el check de disciplina de capital falla
        assert checks["capex_to_da_5y_le_150pct"]["passed"] is False
        # owner earnings: 200 + 100 - 20 - min(300, 100) = 180 > 0, sigue pasando
        assert checks["owner_earnings_5y_positive"]["passed"] is True
    finally:
        db.close()
        cleanup_metric_test_artifacts()


def test_quality_moat_score_v2_esef_approx_roic_and_wacc_without_debt():
    """EUR sin deuda desagregable: roic_gt_wacc se evalua con las
    aproximaciones declaradas ESEF (WACC equity-only, capital invertido
    assets-cash), solo en V2 y solo para EUR."""
    cleanup_metric_test_artifacts()
    db = SessionLocal()
    try:
        company = create_test_company(db)
        company.currency = "EUR"
        add_quality_year_facts(db, company, [2021, 2022, 2023, 2024, 2025])
        add_owner_year_facts(db, company, [2021, 2022, 2023, 2024, 2025])
        for year in (2024, 2025):
            add_fact(db, company, "operating_income", "300", f"FY{year}", year)
            add_fact(db, company, "cash_and_equivalents", "100", f"FY{year}", year)
        add_fact(db, company, "income_tax_expense", "75", "FY2025", 2025)
        add_fact(db, company, "income_before_tax", "300", "FY2025", 2025)
        add_fact(db, company, "risk_free_rate", "0.04", "2025-12-31", 2025, None)
        add_fact(db, company, "beta", "1.2", "2025-12-31", 2025, None)
        add_fact(db, company, "equity_risk_premium", "0.05", "2025-12-31", 2025, None)
        db.commit()

        result = MetricCalculationService().calculate(db, company, "quality_moat_score_v2", persist=True)
        checks = {c["check"]: c for c in result.calculation_trace["checks"]}
        roic_check = checks["roic_gt_wacc"]
        assert roic_check["passed"] is not None
        # WACC equity-only = 0.04 + 1.2*0.05 = 0.10; ROIC aprox = NOPAT/(assets-cash)
        # NOPAT = 300*(1-0.25) = 225; capital medio = 2000-100 = 1900 -> 0.118 > 0.10
        assert Decimal(roic_check["threshold"]) == Decimal("0.10000000")
        assert Decimal(roic_check["value"]) == Decimal("0.11842105")
        assert roic_check["passed"] is True
        assert roic_check["approximation"]["wacc"]["method"] == "wacc_esef_equity_only"
        assert roic_check["approximation"]["roic"]["method"] == "roic_approx_esef_assets_menos_caja"

        # La V1 comparte los checks base: SIN la aproximacion (scope V2).
        v1 = MetricCalculationService().calculate(db, company, "quality_moat_score", persist=False)
        v1_checks = {c["check"]: c for c in v1.calculation_trace["checks"]}
        assert v1_checks["roic_gt_wacc"]["passed"] is None
    finally:
        db.close()
        cleanup_metric_test_artifacts()


def test_quality_moat_score_v2_esef_approx_no_aplica_a_usd():
    """La aproximacion declarada ESEF no se aplica fuera de EUR."""
    cleanup_metric_test_artifacts()
    db = SessionLocal()
    try:
        company = create_test_company(db)  # currency USD por defecto
        add_quality_year_facts(db, company, [2021, 2022, 2023, 2024, 2025])
        add_owner_year_facts(db, company, [2021, 2022, 2023, 2024, 2025])
        for year in (2024, 2025):
            add_fact(db, company, "operating_income", "300", f"FY{year}", year)
            add_fact(db, company, "cash_and_equivalents", "100", f"FY{year}", year)
        add_fact(db, company, "income_tax_expense", "75", "FY2025", 2025)
        add_fact(db, company, "income_before_tax", "300", "FY2025", 2025)
        add_fact(db, company, "risk_free_rate", "0.04", "2025-12-31", 2025, None)
        add_fact(db, company, "beta", "1.2", "2025-12-31", 2025, None)
        add_fact(db, company, "equity_risk_premium", "0.05", "2025-12-31", 2025, None)
        db.commit()

        result = MetricCalculationService().calculate(db, company, "quality_moat_score_v2", persist=True)
        checks = {c["check"]: c for c in result.calculation_trace["checks"]}
        assert checks["roic_gt_wacc"]["passed"] is None
        assert "approximation" not in checks["roic_gt_wacc"]
    finally:
        db.close()
        cleanup_metric_test_artifacts()


def test_ratio_requires_matching_periods_between_numerator_and_denominator():
    """F153: Comparables mostraba net_margin «Objetivo 8.33898622» (~834%)
    porque componia net_income FY2026 con revenue FY2010 (el fallback no
    estricto toma el ultimo hecho de cada metrica sin exigir periodo). Un
    ratio sin coincidencia de periodo es «sin datos», nunca el cociente."""
    cleanup_metric_test_artifacts()
    db = SessionLocal()
    try:
        company = create_test_company(db)
        add_fact(db, company, "net_income", "133750000000", period="2026-06-30:FY", fiscal_year=2026)
        add_fact(db, company, "revenue", "16040000000", period="2010-06-30:FY", fiscal_year=2010)
        db.commit()
        result = MetricCalculationService().calculate(db, company, "net_margin", persist=False)
        assert result.status == "unavailable"
        assert result.value is None
        assert result.calculation_trace["reason"] == "incoherent_periods"
        assert result.calculation_trace["incoherent_inputs"] == {"revenue": "2010-06-30:FY"}
        assert result.calculation_trace["anchor"] == {"metric": "net_income", "period": "2026-06-30:FY"}
    finally:
        db.close()
        cleanup_metric_test_artifacts()


def test_ratio_ok_when_numerator_and_denominator_share_period():
    cleanup_metric_test_artifacts()
    db = SessionLocal()
    try:
        company = create_test_company(db)
        add_fact(db, company, "net_income", "180")
        add_fact(db, company, "revenue", "1000")
        db.commit()
        result = MetricCalculationService().calculate(db, company, "net_margin", persist=False)
        assert result.status == "ok"
        assert result.value == Decimal("0.18000000")
    finally:
        db.close()
        cleanup_metric_test_artifacts()


def test_margin_over_100pct_with_coherent_periods_is_real_and_labeled_atypical():
    """F153: con periodos coherentes, un margen > 100% puede ser un dato
    REAL (venta de activos, reversion fiscal, liberacion de circulante).
    No se declara «sin datos»: se calcula y se etiqueta de atipico con
    numerador y denominador trazados."""
    cleanup_metric_test_artifacts()
    db = SessionLocal()
    try:
        company = create_test_company(db)
        add_fact(db, company, "net_income", "2000")
        add_fact(db, company, "revenue", "1000")
        db.commit()
        result = MetricCalculationService().calculate(db, company, "net_margin", persist=False)
        assert result.status == "ok"
        assert result.value == Decimal("2.00000000")
        assert "margin_over_100pct" in result.calculation_trace["atypical"]
        assert result.numerator == Decimal("2000.00000000")
        assert result.denominator == Decimal("1000.00000000")
    finally:
        db.close()
        cleanup_metric_test_artifacts()


def test_same_fiscal_year_with_different_period_ends_is_not_coherent():
    """F153 (punto 2 del auditor): el fallback fiscal_year/fiscal_quarter no
    puede asociar hechos con cierres distintos dentro del mismo ejercicio."""
    cleanup_metric_test_artifacts()
    db = SessionLocal()
    try:
        company = create_test_company(db)
        add_fact(db, company, "net_income", "180", period="2025-06-30:FY", fiscal_year=2025)
        add_fact(db, company, "revenue", "1000", period="2025-12-31:FY", fiscal_year=2025)
        db.commit()
        result = MetricCalculationService().calculate(db, company, "net_margin", persist=False)
        assert result.status == "unavailable"
        assert result.calculation_trace["reason"] == "incoherent_periods"
        assert result.calculation_trace["incoherent_inputs"] == {"revenue": "2025-12-31:FY"}
    finally:
        db.close()
        cleanup_metric_test_artifacts()


def test_duration_and_instant_facts_sharing_period_end_still_compute():
    """F153 (punto 3 del auditor): las metricas sanas que mezclan flujo y
    saldo instantaneo del mismo cierre (ROE = net_income FY / total_equity
    instantaneo) siguen calculando tras la puerta."""
    cleanup_metric_test_artifacts()
    db = SessionLocal()
    try:
        company = create_test_company(db)
        add_fact(db, company, "net_income", "180", period="2025-06-30:FY", fiscal_year=2025)
        add_fact(db, company, "total_equity", "900", period="2025-06-30:FY", fiscal_year=2025)
        db.commit()
        result = MetricCalculationService().calculate(db, company, "roe", persist=False)
        assert result.status == "ok"
        assert result.value == Decimal("0.20000000")
    finally:
        db.close()
        cleanup_metric_test_artifacts()


def test_same_period_end_but_different_duration_tag_is_not_coherent():
    """Un FY no es un Q4 aunque cierren el mismo dia (leccion F133: duracion
    anual vs trimestral)."""
    cleanup_metric_test_artifacts()
    db = SessionLocal()
    try:
        company = create_test_company(db)
        add_fact(db, company, "net_income", "180", period="2025-06-30:FY", fiscal_year=2025)
        add_fact(db, company, "revenue", "1000", period="2025-06-30:Q4", fiscal_year=None, fiscal_quarter="Q4")
        db.commit()
        result = MetricCalculationService().calculate(db, company, "net_margin", persist=False)
        assert result.status == "unavailable"
        assert result.calculation_trace["reason"] == "incoherent_periods"
    finally:
        db.close()
        cleanup_metric_test_artifacts()


def test_peer_comparison_excludes_atypical_from_median_but_keeps_it_visible():
    """F153 (cierre del auditor): un margen real atipico (200%) queda
    visible con su etiqueta, numerador y denominador, pero NO entra en la
    mediana/promedio del benchmark."""
    cleanup_metric_test_artifacts()
    db = SessionLocal()
    try:
        target = create_test_company(db)
        peer_1 = create_test_company(db, "TPEER1", "Traceable Peer One")
        peer_2 = create_test_company(db, "TPEER2", "Traceable Peer Two")

        for company, revenue, fcf, net_income, operating_income, gross_profit in [
            (target, "1000", "250", "180", "250", "650"),
            (peer_1, "1000", "100", "120", "180", "500"),
            (peer_2, "1000", "300", "2000", "280", "700"),  # margen 200%: real atipico
        ]:
            add_fact(db, company, "revenue", revenue)
            add_fact(db, company, "free_cash_flow", fcf)
            add_fact(db, company, "net_income", net_income)
            add_fact(db, company, "operating_income", operating_income)
            add_fact(db, company, "gross_profit", gross_profit)
        db.commit()
    finally:
        db.close()

    client = csrf_client(main.app)
    response = client.get(f"/api/companies/{TEST_TICKER}/peers/comparison?metrics=net_margin&limit=2")
    assert response.status_code == 200
    payload = response.json()

    bench = payload["benchmarks"]["net_margin"]
    # Solo TPEER1 (0,12) entra en la mediana; TPEER2 (2,0) queda fuera pero visible.
    assert bench["peer_median"] is None  # F26: n=1 < 3, sin mediana
    assert bench["insufficient_sample"] is True
    assert bench["peer_sample_size"] == 1
    assert len(bench["excluded_atypical"]) == 1
    excluded = bench["excluded_atypical"][0]
    assert excluded["ticker"] == "TPEER2"
    assert Decimal(excluded["value"]) == Decimal("2.00000000")
    assert "margin_over_100pct" in excluded["atypical"]

    peer2_row = next(row for row in payload["companies"] if row["ticker"] == "TPEER2")
    metric_payload = peer2_row["metrics"]["net_margin"]
    assert metric_payload["status"] == "ok"
    assert Decimal(metric_payload["value"]) == Decimal("2.00000000")
    assert "margin_over_100pct" in metric_payload["atypical"]
    assert Decimal(metric_payload["numerator"]) == Decimal("2000.00000000")
    assert Decimal(metric_payload["denominator"]) == Decimal("1000.00000000")
    assert metric_payload["calculation_trace"]["atypical"]

    cleanup_metric_test_artifacts()


def test_peer_benchmark_with_three_peers_and_peer_without_data():
    """F26: n>=3 calcula mediana; un comparable sin metricas no cuenta."""
    cleanup_metric_test_artifacts()
    extra = ["TPEER3", "TPEER4"]
    db = SessionLocal()
    try:
        target = create_test_company(db)
        peers = [create_test_company(db, t, f"Peer {t}") for t in ["TPEER1", "TPEER2", *extra]]
        for company, revenue, fcf, net_income, operating_income, gross_profit in [
            (target, "1000", "250", "180", "250", "650"),
            (peers[0], "1000", "100", "120", "180", "500"),
            (peers[1], "1000", "200", "220", "280", "700"),
            (peers[2], "1000", "300", "320", "380", "800"),
        ]:
            add_fact(db, company, "revenue", revenue)
            add_fact(db, company, "free_cash_flow", fcf)
            add_fact(db, company, "net_income", net_income)
            add_fact(db, company, "operating_income", operating_income)
            add_fact(db, company, "gross_profit", gross_profit)
        db.commit()
    finally:
        db.close()
    try:
        client = csrf_client(main.app)
        response = client.get(f"/api/companies/{TEST_TICKER}/peers/comparison?metrics=fcf_margin&limit=4")
        assert response.status_code == 200
        payload = response.json()
        bench = payload["benchmarks"]["fcf_margin"]
        assert payload["peer_count"] == 3
        assert payload["peers_without_data"] == ["TPEER4"]
        assert bench["insufficient_sample"] is False and bench["note"] is None
        assert bench["peer_sample_size"] == 3
        assert Decimal(bench["peer_median"]) == Decimal("0.20000000")
        assert Decimal(bench["target_vs_peer_median"]) == Decimal("0.05000000")
    finally:
        db = SessionLocal()
        try:
            for company in db.scalars(select(Company).where(Company.ticker.in_(extra))).all():
                db.execute(delete(CalculatedMetric).where(CalculatedMetric.company_id == company.id))
                db.execute(delete(FinancialFact).where(FinancialFact.company_id == company.id))
                db.delete(company)
            db.commit()
        finally:
            db.close()
        cleanup_metric_test_artifacts()


def test_owner_earnings_unit_follows_input_currency():
    cleanup_metric_test_artifacts()
    db = SessionLocal()
    try:
        company = create_test_company(db)
        for metric, val in (("net_income", "200"), ("depreciation_amortization", "80"), ("capital_expenditure", "-120"), ("change_in_working_capital", "-30")):
            fact = add_fact(db, company, metric, val)
            fact.unit = "CAD"
        db.commit()
        result = MetricCalculationService().calculate(db, company, "owner_earnings", persist=False)
        assert result.status == "ok"
        assert result.unit == "CAD"
    finally:
        db.close()
        cleanup_metric_test_artifacts()


def test_owner_earnings_mixed_currency_is_unavailable():
    cleanup_metric_test_artifacts()
    db = SessionLocal()
    try:
        company = create_test_company(db)
        for metric, val, unit in (("net_income", "200", "CAD"), ("depreciation_amortization", "80", "USD"), ("capital_expenditure", "-120", "USD"), ("change_in_working_capital", "-30", "USD")):
            add_fact(db, company, metric, val).unit = unit
        db.commit()
        result = MetricCalculationService().calculate(db, company, "owner_earnings", persist=False)
        assert result.status == "unavailable"
        assert result.value is None
        assert result.calculation_trace["reason"] == "mixed_currency_inputs"
    finally:
        db.close()
        cleanup_metric_test_artifacts()


def test_fcf_before_growth_capex_ok_declared_estimate():
    cleanup_metric_test_artifacts()
    db = SessionLocal()
    try:
        company = create_test_company(db)
        add_fact(db, company, "free_cash_flow", "100")
        add_fact(db, company, "capital_expenditure", "-120")
        add_fact(db, company, "depreciation_amortization", "80")
        db.commit()

        service = MetricCalculationService()
        result = service.calculate(db, company, "fcf_before_growth_capex", persist=True)
        db.commit()
        # maintenance = min(120, 80) = 80; growth = 40; FCF antes de crecimiento = 140
        assert result.status == "ok"
        assert result.definition_version == "FCF_BEFORE_GROWTH_CAPEX_V1"
        assert result.value == Decimal("140.00000000")
        assert result.calculation_trace["maintenance_capex"] == "80.00000000"
        assert result.calculation_trace["estimated_growth_capex"] == "40.00000000"
        assert "declared" in result.calculation_trace["maintenance_capex_rule"]
        assert "estimate" in result.calculation_trace

        # capex por debajo de D&A: growth = 0, el valor coincide con el FCF
        db.execute(
            delete(FinancialFact).where(
                FinancialFact.company_id == company.id,
                FinancialFact.metric == "capital_expenditure",
            )
        )
        add_fact(db, company, "capital_expenditure", "-50")
        db.commit()
        result2 = service.calculate(db, company, "fcf_before_growth_capex", persist=False)
        assert result2.status == "ok"
        assert result2.value == Decimal("100.00000000")
        assert Decimal(result2.calculation_trace["estimated_growth_capex"]) == 0
    finally:
        db.close()
        cleanup_metric_test_artifacts()


def test_fcf_before_growth_capex_partial_without_da():
    cleanup_metric_test_artifacts()
    db = SessionLocal()
    try:
        company = create_test_company(db)
        add_fact(db, company, "free_cash_flow", "100")
        add_fact(db, company, "capital_expenditure", "-120")
        db.commit()

        result = MetricCalculationService().calculate(
            db, company, "fcf_before_growth_capex", persist=False
        )
        # Sin D&A no hay separacion y no se publica un valor sustitutivo
        assert result.status == "partial"
        assert result.value is None
        assert result.calculation_trace["reason"] == "growth_capex_not_separable"
        assert "depreciation_amortization" in result.calculation_trace["missing_inputs"]
        assert "no_value_without_split" in result.calculation_trace["value_basis"]
    finally:
        db.close()
        cleanup_metric_test_artifacts()


def test_fcf_before_growth_capex_unavailable_without_capex_or_fcf():
    cleanup_metric_test_artifacts()
    db = SessionLocal()
    try:
        company = create_test_company(db)
        add_fact(db, company, "depreciation_amortization", "80")
        db.commit()

        service = MetricCalculationService()
        result = service.calculate(db, company, "fcf_before_growth_capex", persist=False)
        assert result.status == "insufficient_data"
        assert result.value is None
        assert "free_cash_flow" in result.calculation_trace["missing_inputs"]

        add_fact(db, company, "free_cash_flow", "100")
        db.commit()
        result2 = service.calculate(db, company, "fcf_before_growth_capex", persist=False)
        assert result2.status == "insufficient_data"
        assert "capital_expenditure" in result2.calculation_trace["missing_inputs"]
    finally:
        db.close()
        cleanup_metric_test_artifacts()


def test_fcf_before_growth_capex_unit_follows_input_currency():
    cleanup_metric_test_artifacts()
    db = SessionLocal()
    try:
        company = create_test_company(db)
        for metric, val in (("free_cash_flow", "100"), ("capital_expenditure", "-120"), ("depreciation_amortization", "80")):
            fact = add_fact(db, company, metric, val)
            fact.unit = "EUR"
        db.commit()
        result = MetricCalculationService().calculate(
            db, company, "fcf_before_growth_capex", persist=False
        )
        assert result.status == "ok"
        assert result.unit == "EUR"
    finally:
        db.close()
        cleanup_metric_test_artifacts()


def test_fcf_before_growth_capex_mixed_currency_is_unavailable():
    cleanup_metric_test_artifacts()
    db = SessionLocal()
    try:
        company = create_test_company(db)
        for metric, val, unit in (("free_cash_flow", "100", "EUR"), ("capital_expenditure", "-120", "USD"), ("depreciation_amortization", "80", "USD")):
            add_fact(db, company, metric, val).unit = unit
        db.commit()
        result = MetricCalculationService().calculate(
            db, company, "fcf_before_growth_capex", persist=False
        )
        assert result.status == "insufficient_data"
        assert result.value is None
        assert result.calculation_trace["reason"] == "mixed_currency_inputs"
    finally:
        db.close()
        cleanup_metric_test_artifacts()


def test_fcf_before_growth_capex_rejects_negative_da_and_mixed_periods():
    cleanup_metric_test_artifacts()
    db = SessionLocal()
    try:
        company = create_test_company(db)
        add_fact(db, company, "free_cash_flow", "100")
        add_fact(db, company, "capital_expenditure", "-120")
        dna = add_fact(db, company, "depreciation_amortization", "-80")
        db.commit()
        service = MetricCalculationService()
        result = service.calculate(db, company, "fcf_before_growth_capex", persist=False)
        assert result.value is None
        assert result.calculation_trace["reason"] == "invalid_inputs"
        dna.value = Decimal("80")
        dna.period = "FY2024"
        dna.fiscal_year = 2024
        db.commit()
        result = service.calculate(db, company, "fcf_before_growth_capex", persist=False)
        assert result.value is None
        assert result.calculation_trace["reason"] == "incoherent_periods"
    finally:
        db.close()
        cleanup_metric_test_artifacts()


def test_fcf_before_growth_capex_rejects_nonfinite_before_arithmetic(monkeypatch):
    cleanup_metric_test_artifacts()
    db = SessionLocal()
    try:
        company = create_test_company(db)
        facts = {metric: add_fact(db, company, metric, value) for metric, value in (
            ("free_cash_flow", "100"), ("capital_expenditure", "-120"),
            ("depreciation_amortization", "80"),
        )}
        db.commit()
        service = MetricCalculationService()
        # In-memory corrupt provider payload, never written to SQLite.
        for metric in facts:
            for invalid in ("NaN", "Infinity", "-Infinity"):
                original = facts[metric].value
                facts[metric].value = Decimal(invalid)
                monkeypatch.setattr(service, "_coherent_facts", lambda *args: facts)
                result = service.calculate(db, company, "fcf_before_growth_capex", persist=False)
                assert result.status == "insufficient_data"
                assert result.value is None
                facts[metric].value = original
    finally:
        db.rollback()
        db.close()
        cleanup_metric_test_artifacts()
