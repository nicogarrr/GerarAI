import time
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import (
    CalculatedMetric,
    Company,
    FinancialFact,
    ResearchAlert,
    Tenant,
)
from app.services.screener_service import (
    CustomMetricService,
    SafeFormula,
    ScreenerService,
)


def _company(ticker: str) -> Company:
    return Company(
        ticker=ticker,
        name=f"{ticker} Co",
        exchange="TEST",
        currency="USD",
        sector="Test",
        industry="Test",
        company_type="standard",
        valuation_model="standard_dcf",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )


def _metric(db: Session, company: Company, metric: str, value: str) -> None:
    db.add(
        CalculatedMetric(
            company_id=company.id,
            metric=metric,
            value=Decimal(value),
            unit="decimal",
            period="FY2025",
            fiscal_year=2025,
            status="ok",
            definition_version="test-v1",
            formula=metric,
            source_fact_ids=[],
            calculation_trace={},
            confidence=Decimal("0.9"),
        )
    )


def _fact(db: Session, company: Company, metric: str, value: str, year: int) -> None:
    db.add(
        FinancialFact(
            company_id=company.id,
            metric=metric,
            value=Decimal(value),
            unit="USD" if metric == "free_cash_flow" else "shares",
            period=f"FY{year}",
            fiscal_year=year,
            fiscal_quarter="FY",
            source_type="sec_filing",
            confidence=Decimal("0.95"),
        )
    )


def test_custom_metric_screen_reports_quality_and_alerts_only_new_matches():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        tenant = Tenant(external_id="screen-test", name="Screen test")
        db.add(tenant)
        db.flush()
        db.info["tenant_id"] = tenant.id
        compounder = _company("CMPD")
        incomplete = _company("MISS")
        db.add_all([compounder, incomplete])
        db.flush()
        _metric(db, compounder, "roic", "0.18")
        _metric(db, compounder, "wacc", "0.08")
        _metric(db, compounder, "net_debt_to_ebitda", "1.2")
        _metric(db, incomplete, "roic", "0.15")
        for company, first_fcf, last_fcf in (
            (compounder, "10", "20"),
            (incomplete, "10", "11"),
        ):
            _fact(db, company, "free_cash_flow", first_fcf, 2020)
            _fact(db, company, "free_cash_flow", last_fcf, 2025)
            _fact(db, company, "shares_diluted", "10", 2020)
            _fact(db, company, "shares_diluted", "10", 2025)
        db.commit()

        definition = CustomMetricService().create(
            db,
            metric_key="roic_spread",
            name="ROIC spread",
            formula="roic - wacc",
            unit="decimal",
            description="ROIC less WACC",
        )
        assert definition.metadata_["dependencies"] == ["roic", "wacc"]
        criteria = [
            {"left": "roic_spread", "operator": ">", "right": "0.05"},
            {
                "left": "fcf_per_share_cagr",
                "operator": ">",
                "right": "0.08",
            },
            {"left": "shares_cagr", "operator": "<", "right": "0.02"},
            {
                "left": "net_debt_to_ebitda",
                "operator": "<",
                "right": "2",
            },
        ]
        screen = ScreenerService().create_screen(
            db,
            name="Quality compounders",
            description="Evidence-aware compounder screen",
            criteria=criteria,
            ranking_formula="roic_spread + fcf_per_share_cagr",
            ranking_direction="desc",
            alerts_enabled=True,
        )

        first = ScreenerService().run_saved(db, screen)
        second = ScreenerService().run_saved(db, screen)

        match = next(row for row in first["results"] if row["ticker"] == "CMPD")
        missing = next(row for row in first["results"] if row["ticker"] == "MISS")
        assert match["matched"] is True
        assert match["coverage_percent"] == 100
        assert Decimal(match["confidence"]) > Decimal("0.8")
        assert match["latest_data_at"] is not None
        assert missing["matched"] is False
        assert {"wacc", "net_debt_to_ebitda", "roic_spread"} <= set(missing["missing_fields"])
        assert first["new_match_company_ids"] == [compounder.id]
        assert second["new_match_company_ids"] == []
        assert len(db.scalars(select(ResearchAlert)).all()) == 1


def test_formula_engine_rejects_code_execution_constructs():
    with pytest.raises(ValueError, match="admiten|permitido"):
        SafeFormula("__import__('os').system('whoami')")


def test_ranking_dependencies_are_included_in_result_quality():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        tenant = Tenant(external_id="ranking-quality", name="Ranking quality")
        db.add(tenant)
        db.flush()
        db.info["tenant_id"] = tenant.id
        complete = _company("COMP")
        missing = _company("MISS")
        db.add_all([complete, missing])
        db.flush()
        for company in (complete, missing):
            _metric(db, company, "roic", "0.18")
        _metric(db, complete, "quality_score", "0.75")
        db.commit()

        response = ScreenerService().run(
            db,
            criteria=[{"left": "roic", "operator": ">", "right": "0.1"}],
            ranking_formula="quality_score",
            ranking_direction="asc",
        )

        complete_result = next(row for row in response["results"] if row["ticker"] == "COMP")
        missing_result = next(row for row in response["results"] if row["ticker"] == "MISS")
        assert complete_result["matched"] is True
        assert complete_result["coverage_percent"] == 100
        # La formula de ranking ordena, no filtra: MISS cumple el unico criterio
        # (roic 0.18 > 0.1) asi que entra en el screen, aunque no se pueda
        # ordenar. La dependencia que falta se sigue declarando en la calidad
        # del resultado (coverage 50, missing_fields) para no ocultarla.
        assert missing_result["matched"] is True
        assert missing_result["coverage_percent"] == 50
        assert missing_result["missing_fields"] == ["quality_score"]
        assert response["results"][0]["ticker"] == "COMP"


def test_screen_query_count_is_constant_in_company_count():
    """The screener evaluates every company; its query count must not grow
    with the company count (2 queries per company became 2 total)."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        tenant = Tenant(external_id="screen-count", name="Screen count")
        db.add(tenant)
        db.flush()
        db.info["tenant_id"] = tenant.id
        for index in range(6):
            company = _company(f"C{index:02d}")
            db.add(company)
            db.flush()
            _metric(db, company, "roic", "0.18")
            _fact(db, company, "free_cash_flow", "10", 2024)
            _fact(db, company, "free_cash_flow", "20", 2025)
        db.commit()

        from sqlalchemy import event

        statements = []

        def listener(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        event.listen(engine, "before_cursor_execute", listener)
        try:
            result = ScreenerService().run(
                db,
                criteria=[{"left": "roic", "operator": ">", "right": "0.05"}],
            )
        finally:
            event.remove(engine, "before_cursor_execute", listener)

        assert result["results"]
        metric_queries = [s for s in statements if "calculated_metrics" in s]
        fact_queries = [s for s in statements if "financial_facts" in s]
        assert len(metric_queries) == 1
        assert len(fact_queries) == 1


def test_metric_coverage_lists_only_metrics_with_data():
    # The datalist suggests only metrics at least one company has data for;
    # suggesting a metric nobody has (e.g. wacc before it is ingested) can
    # only produce the "no company has data" outcome.
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        tenant = Tenant(external_id="coverage-test", name="Coverage test")
        db.add(tenant)
        db.flush()
        db.info["tenant_id"] = tenant.id
        company = _company("COV")
        db.add(company)
        db.flush()
        _metric(db, company, "roic", "0.15")
        _fact(db, company, "revenue", "1000", 2025)
        db.add(
            CalculatedMetric(
                company_id=company.id,
                metric="wacc",
                value=None,
                unit="decimal",
                period="FY2025",
                fiscal_year=2025,
                status="missing_inputs",
                definition_version="test-v1",
                formula="wacc",
                source_fact_ids=[],
                calculation_trace={},
                confidence=Decimal("0"),
            )
        )
        db.commit()
        coverage = ScreenerService().metric_coverage(db)
    assert "roic" in coverage
    assert "revenue" in coverage
    assert "wacc" not in coverage



def test_metric_coverage_caches_per_tenant(monkeypatch):
    # La lectura agrega sobre tablas grandes (>15 s en frio en prod): la
    # segunda llamada dentro del TTL no reconsulta.
    from app.services import screener_service

    screener_service._METRIC_COVERAGE_CACHE.clear()
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.info["tenant_id"] = 424242
    try:
        company = _company("COVCACHE")
        db.add(company)
        db.flush()
        _metric(db, company, "roic", "0.15")
        db.commit()

        service = ScreenerService()
        first = service.metric_coverage(db)
        assert "roic" in first

        # Nuevo dato tras la primera lectura: no aparece hasta expirar el TTL.
        _metric(db, company, "fcf_yield", "0.04")
        db.commit()
        assert service.metric_coverage(db) == first

        # TTL expirado (reloj adelantado): reconsulta y ve el dato nuevo.
        real_monotonic = time.monotonic
        monkeypatch.setattr(
            screener_service.time, "monotonic", lambda: real_monotonic() + 3600
        )
        assert "fcf_yield" in service.metric_coverage(db)
    finally:
        screener_service._METRIC_COVERAGE_CACHE.clear()
        db.close()


def test_fcf_per_share_cagr_ignores_quarterly_rows_like_plain_cagr():
    """Un trimestre ingerido después del anual no es el FCF del año.

    `_cagr` ya filtraba los trimestres; `_ratio_cagr` no, así que el Q3 de
    2024 (50) sustituía al anual (200) y el CAGR salía negativo.
    """
    def fact(fid, metric, value, year, quarter):
        return FinancialFact(
            id=fid, company_id=1, metric=metric, value=Decimal(value), period=f"{quarter}{year}",
            fiscal_year=year, fiscal_quarter=quarter, confidence=Decimal("0.9"),
        )

    # Orden de la consulta: fiscal_year DESC, id DESC (el más nuevo primero).
    fcf = [fact(4, "free_cash_flow", "50", 2024, "Q3"), fact(3, "free_cash_flow", "200", 2024, "FY"),
           fact(1, "free_cash_flow", "100", 2020, "FY")]
    shares = [fact(5, "shares_diluted", "10", 2024, "FY"), fact(2, "shares_diluted", "10", 2020, "FY")]

    plain = ScreenerService._cagr(fcf)
    ratio = ScreenerService()._ratio_cagr(fcf, shares)

    expected = (Decimal(2) ** (Decimal(1) / 4)) - 1  # 10 -> 20 por acción en 4 años
    assert plain is not None and abs(plain.value - expected) < Decimal("0.000001")
    assert ratio is not None and abs(ratio.value - expected) < Decimal("0.000001")



def test_point_value_prefers_the_annual_row_over_a_later_quarter():
    """El valor puntual sigue la misma regla que `_cagr`: el anual manda."""
    def fact(fid, value, year, quarter):
        return FinancialFact(
            id=fid, company_id=1, metric="free_cash_flow", value=Decimal(value), period=f"{quarter}{year}",
            fiscal_year=year, fiscal_quarter=quarter, confidence=Decimal("0.9"),
        )

    service = ScreenerService()
    mixed = service._observations_from_rows([], [fact(3, "50", 2024, "Q3"), fact(2, "200", 2023, "FY")])
    assert mixed["free_cash_flow"].value == Decimal("200")
    assert mixed["free_cash_flow"].period == "FY2023"
    # Sin ninguna fila anual se usa la más reciente, como antes.
    only_quarters = service._observations_from_rows([], [fact(3, "50", 2024, "Q3"), fact(1, "40", 2024, "Q2")])
    assert only_quarters["free_cash_flow"].value == Decimal("50")
