from decimal import Decimal

import pytest
from sqlalchemy import delete, select

import main
from app.core.database import SessionLocal, init_db
from app.models import CalculatedMetric, Company, FinancialFact, Position
from app.services.long_term_model_service import LongTermModelService
from tests.auth_helpers import csrf_client

TICKER = "TLM"


def _cleanup() -> None:
    init_db()
    db = SessionLocal()
    try:
        company = db.scalar(select(Company).where(Company.ticker == TICKER))
        if company:
            db.execute(delete(FinancialFact).where(FinancialFact.company_id == company.id))
            db.execute(delete(Position).where(Position.company_id == company.id))
            db.delete(company)
            db.commit()
    finally:
        db.close()


def _fact(db, company, metric: str, value: float, year: int) -> None:
    db.add(
        FinancialFact(
            company_id=company.id,
            metric=metric,
            value=Decimal(str(value)),
            unit="shares" if metric == "shares_diluted" else "USD",
            period=f"FY{year}",
            fiscal_year=year,
            fiscal_quarter="FY",
            source_type="test_long_term",
            is_reported=True,
            confidence=Decimal("0.95"),
        )
    )


def test_long_term_model_returns_scenarios_and_source_trace():
    _cleanup()
    db = SessionLocal()
    try:
        company = Company(
            ticker=TICKER,
            name="Long Term Model Test Co",
            exchange="TEST",
            currency="USD",
            sector="Software",
            industry="Application Software",
            company_type="standard",
            valuation_model="standard_dcf",
            special_sources=[],
            special_risks=[],
            factor_tags=["quality"],
        )
        db.add(company)
        db.flush()
        db.add(Position(company_id=company.id, market_price=Decimal("50")))
        for year, revenue, fcf, shares in [
            (2020, 100, 20, 10.0),
            (2021, 110, 22, 9.9),
            (2022, 121, 25, 9.8),
            (2023, 133, 28, 9.7),
            (2024, 146, 31, 9.5),
            (2025, 160, 35, 9.3),
        ]:
            _fact(db, company, "revenue", revenue, year)
            _fact(db, company, "gross_profit", revenue * 0.60, year)
            _fact(db, company, "operating_income", revenue * 0.20, year)
            _fact(db, company, "ebitda", revenue * 0.25, year)
            _fact(db, company, "net_income", revenue * 0.15, year)
            _fact(db, company, "free_cash_flow", fcf, year)
            _fact(db, company, "operating_cash_flow", fcf + 8, year)
            _fact(db, company, "capital_expenditure", -8, year)
            _fact(db, company, "shares_diluted", shares, year)
            _fact(db, company, "net_debt", 50 - (year - 2020) * 2, year)
            _fact(db, company, "total_debt", 100, year)
            _fact(db, company, "total_equity", 300, year)
            _fact(db, company, "cash_and_equivalents", 50, year)
            _fact(db, company, "market_size", 1000 * (1.05 ** (year - 2020)), year)
            _fact(db, company, "market_growth", 0.05, year)
        db.add(
            CalculatedMetric(
                company_id=company.id,
                metric="wacc",
                value=Decimal("0.09"),
                unit="decimal",
                period="FY2025",
                fiscal_year=2025,
                status="ok",
                definition_version="wacc-v1",
                formula="E/(D+E)*cost_of_equity + D/(D+E)*after_tax_cost_of_debt",
                source_fact_ids=[],
                calculation_trace={"risk_free_rate": 0.04, "equity_risk_premium": 0.05},
                confidence=Decimal("0.90"),
            )
        )
        db.commit()
    finally:
        db.close()

    response = csrf_client(main.app).post(
        f"/api/companies/{TICKER}/long-term-model/generate?horizon=5"
    )
    assert response.status_code == 200
    payload = response.json()

    assert payload["status"] == "ok"
    assert payload["publishable"] is True
    assert payload["model_version"] == "long-term-fundamental-model-v2"
    assert payload["algorithm_version"] == "driver-formulas-funding-rollforward-v2"
    assert payload["historical_review"]["years_covered"] == 6
    assert len(payload["scenarios"]["base"]["forecast"]) == 5
    assert payload["scenarios"]["base"]["year_5"]["free_cash_flow"] > 0
    assert payload["scenarios"]["base"]["valuation"]["value_per_share"] > 0
    assert payload["framework"]["key"] == "generic_fcf"
    assert payload["market_opportunity"]["status"] == "ok"
    assert payload["market_opportunity"]["top_down"]["tam"]["value"] > 0
    assert payload["market_opportunity"]["implied_by_valuation"]["base_future_market_share"] > 0
    assert payload["market_opportunity"]["source_fact_ids"]
    assert payload["assumptions"]["revenue_growth"]["source_fact_ids"]
    assert payload["scenarios"]["base"]["forecast"][0]["evidence"]["free_cash_flow"]["source_fact_ids"]
    assert payload["driver_formula"]["formula_key"] == "reported_revenue_bridge"
    assert payload["scenarios"]["base"]["driver_operating_model"]["status"] == "driver_based"
    first_forecast = payload["scenarios"]["base"]["forecast"][0]
    assert first_forecast["funding_model"]["debt_trend_status"] == "historical_cagr"
    assert first_forecast["invested_capital"] > 350
    assert first_forecast["evidence"]["roic"]["calculation"] == "NOPAT / rolled-forward invested capital"
    assert payload["trace"]["wacc"]["status"] == "traceable"
    assert payload["owner_earnings"]["status"] == "insufficient_data"
    assert "maintenance_vs_growth_capex_split" in payload["limitations"]

    _cleanup()


# --------------------------------------------------------------------------
# FCF = OCF + capex is one rule; each caller wraps it in its own return shape
# --------------------------------------------------------------------------


def _row(metric: str, year: int, value, fact_id: int) -> FinancialFact:
    return FinancialFact(
        id=fact_id, company_id=1, metric=metric, value=value, unit="USD",
        period=f"FY{year}", fiscal_year=year, fiscal_quarter="FY",
    )


def _cache(ocf: FinancialFact | None, capex: FinancialFact | None) -> dict:
    return {
        "free_cash_flow": [],
        "operating_cash_flow": [ocf] if ocf else [],
        "capital_expenditure": [capex] if capex else [],
    }


def test_derived_fcf_is_ocf_plus_signed_capex():
    service = LongTermModelService()
    cache = _cache(
        _row("operating_cash_flow", 2024, Decimal("120"), 1),
        _row("capital_expenditure", 2024, Decimal("-30"), 2),
    )
    assert service._derived_fcf_value(cache, 2024) == pytest.approx(90.0)
    assert service._derived_fcf_series(cache, [2024]) == [
        {"year": 2024, "value": pytest.approx(90.0), "fact_ids": [1, 2]}
    ]


def test_derived_fcf_is_not_declared_when_a_leg_is_unreadable():
    """A leg with no readable value is not a zero.

    Reporting the surviving leg alone (120) or a flat 0 published a cash flow
    the issuer never reported, indistinguishable from a verified one.
    """
    service = LongTermModelService()
    for cache in (
        _cache(_row("operating_cash_flow", 2024, None, 1), _row("capital_expenditure", 2024, Decimal("-30"), 2)),
        _cache(_row("operating_cash_flow", 2024, Decimal("120"), 1), _row("capital_expenditure", 2024, None, 2)),
        _cache(_row("operating_cash_flow", 2024, Decimal("120"), 1), None),
    ):
        assert service._derived_fcf_value(cache, 2024) is None
        assert service._derived_fcf_series(cache, [2024]) == []


def test_reverse_dcf_missing_inputs_names_only_what_is_missing():
    from types import SimpleNamespace

    from app.services.long_term_model_service import LongTermModelService

    service = LongTermModelService()
    assumptions = {
        "fcf_margin": SimpleNamespace(value=0.15, source_fact_ids=[]),
        "wacc": SimpleNamespace(value=0.1, source_fact_ids=[]),
        "terminal_growth": SimpleNamespace(value=0.02, source_fact_ids=[]),
        "revenue_growth": SimpleNamespace(value=0.2, source_fact_ids=[]),
    }
    service._value_for_year = lambda facts, year: {  # type: ignore[method-assign]
        "revenue": 100.0, "shares_diluted": 10.0, "net_debt": None,
    }[facts]
    result = service._reverse_dcf(
        current_price=40.65,
        assumptions=assumptions,
        fact_cache={"revenue": "revenue", "shares_diluted": "shares_diluted", "net_debt": "net_debt"},
        horizon=5,
        source_year=2025,
    )
    assert result["status"] == "insufficient_data"
    assert result["missing_inputs"] == ["net_debt"]
