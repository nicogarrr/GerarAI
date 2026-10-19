"""ProPicks funnel v1: gates, sector branch, coverage honesty, persistence."""

from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import (
    CalculatedMetric,
    Company,
    FinancialFact,
    ProPickCandidate,
    ProPickRun,
    Tenant,
)
from app.services.propicks_funnel_service import (
    COVERAGE_METRICS,
    execute_run,
    run_funnel,
)


def _company(ticker: str, sector: str = "Industrials", currency: str = "USD") -> Company:
    return Company(
        ticker=ticker,
        name=f"{ticker} Co",
        exchange="TEST",
        currency=currency,
        sector=sector,
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
            unit="USD",
            period=f"FY{year}",
            fiscal_year=year,
            fiscal_quarter="FY",
            source_type="sec_filing",
            confidence=Decimal("0.95"),
        )
    )


GOOD_METRICS = {
    "roic": "0.20",
    "cfroi_approx": "0.16",
    "wacc": "0.08",
    "fcf_margin_5y": "0.12",
    "owner_earnings_5y": "100",
    "roe_5y": "0.18",
    "net_margin_5y": "0.15",
    "roa_5y": "0.10",
    "capex_to_da_5y": "1.0",
    "quality_moat_score_v2": "0.7",
    "net_debt_to_ebitda": "1.0",
    "fcf_conversion": "0.9",
}


def _full_metrics(db: Session, company: Company, overrides: dict | None = None) -> None:
    for metric, value in (GOOD_METRICS | (overrides or {})).items():
        _metric(db, company, metric, value)


def _five_good_years(db: Session, company: Company) -> None:
    for year in range(2021, 2026):
        _fact(db, company, "net_income", "100", year)
        _fact(db, company, "revenue", str(1000 + (year - 2021) * 100), year)


def _db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    tenant = Tenant(external_id="funnel-test", name="Funnel test")
    db.add(tenant)
    db.flush()
    db.info["tenant_id"] = tenant.id
    return db


def test_quality_company_passes_and_scores():
    with _db() as db:
        good = _company("GOOD")
        db.add(good)
        db.flush()
        _full_metrics(db, good)
        _five_good_years(db, good)
        db.commit()

        results, stats = run_funnel(db)
        assert stats["universe_size"] == 1
        assert stats["passed_count"] == 1
        result = results[0]
        assert result.passed
        assert result.failed_gates == []
        assert result.score is not None and 0 <= result.score <= 100
        assert result.coverage["roic"] == "ok"
        assert result.coverage["net_debt_to_ebitda"] == "ok"


def test_roic_below_wacc_fails_for_non_financial():
    with _db() as db:
        value_trap = _company("TRAP")
        db.add(value_trap)
        db.flush()
        _full_metrics(db, value_trap, {"roic": "0.05"})
        _five_good_years(db, value_trap)
        db.commit()

        (result,), _ = run_funnel(db)
        assert not result.passed
        assert any(g.startswith("roic:") for g in result.failed_gates)


def test_financial_branch_uses_roe_not_roic():
    with _db() as db:
        bank = _company("BANK", sector="Financials", currency="EUR")
        db.add(bank)
        db.flush()
        # roic below wacc: would fail the non-financial gate, must pass here.
        _full_metrics(db, bank, {"roic": "0.01", "cfroi_approx": "0.01", "roe_5y": "0.15"})
        _five_good_years(db, bank)
        db.commit()

        (result,), _ = run_funnel(db)
        assert result.passed
        assert result.coverage["quality_gate"].startswith("approx:financials")
        assert result.components["spread_roic_wacc"] is None

        weak_bank = _company("WEAKBANK", sector="Financials", currency="EUR")
        db.add(weak_bank)
        db.flush()
        _full_metrics(db, weak_bank, {"roe_5y": "0.05"})
        _five_good_years(db, weak_bank)
        db.commit()

        results, _ = run_funnel(db)
        weak = next(r for r in results if r.company_id == weak_bank.id)
        assert not weak.passed
        assert any(g.startswith("quality_gate:roe") for g in weak.failed_gates)


def test_leverage_and_consistency_gates():
    with _db() as db:
        levered = _company("LEVER")
        cyclical = _company("CYCL")
        db.add_all([levered, cyclical])
        db.flush()
        _full_metrics(db, levered, {"net_debt_to_ebitda": "4.5"})
        _five_good_years(db, levered)
        _full_metrics(db, cyclical)
        for year, ni in ((2021, "100"), (2022, "-50"), (2023, "100"), (2024, "-80"), (2025, "90")):
            _fact(db, cyclical, "net_income", ni, year)
            _fact(db, cyclical, "revenue", "1000", year)
        db.commit()

        results, _ = run_funnel(db)
        by_ticker = {r.company_id: r for r in results}
        assert not by_ticker[levered.id].passed
        assert any(g.startswith("leverage:") for g in by_ticker[levered.id].failed_gates)
        assert not by_ticker[cyclical.id].passed
        assert any(g.startswith("consistency:") for g in by_ticker[cyclical.id].failed_gates)


def test_missing_leverage_metric_is_declared_not_applied():
    with _db() as db:
        eur = _company("EURE", currency="EUR")
        db.add(eur)
        db.flush()
        metrics = dict(GOOD_METRICS)
        del metrics["net_debt_to_ebitda"]
        for metric, value in metrics.items():
            _metric(db, eur, metric, value)
        _five_good_years(db, eur)
        db.commit()

        (result,), _ = run_funnel(db)
        assert result.passed
        assert result.coverage["net_debt_to_ebitda"] == "missing"


def test_low_coverage_fails():
    with _db() as db:
        thin = _company("THIN")
        db.add(thin)
        db.flush()
        for metric in list(COVERAGE_METRICS)[:5]:
            _metric(db, thin, metric, "0.1")
        _metric(db, thin, "wacc", "0.08")
        _five_good_years(db, thin)
        db.commit()

        (result,), _ = run_funnel(db)
        assert not result.passed
        assert any(g.startswith("coverage:") for g in result.failed_gates)


def test_execute_run_persists_run_and_candidates():
    with _db() as db:
        good = _company("GOOD")
        bad = _company("BAD")
        db.add_all([good, bad])
        db.flush()
        _full_metrics(db, good)
        _five_good_years(db, good)
        _full_metrics(db, bad, {"roic": "0.01", "cfroi_approx": "0.01"})
        _five_good_years(db, bad)
        db.commit()

        run = execute_run(db, top_n=10)
        assert run.id is not None
        assert run.universe_size == 2
        assert run.passed_count == 1
        assert run.funnel_version.startswith("propicks-funnel")

        rows = db.scalars(
            select(ProPickCandidate).where(ProPickCandidate.run_id == run.id)
        ).all()
        assert len(rows) == 2
        winner = next(r for r in rows if r.company_id == good.id)
        assert winner.passed and winner.rank == 1 and winner.score is not None
        loser = next(r for r in rows if r.company_id == bad.id)
        assert not loser.passed and loser.rank is None
        assert loser.failed_gates

        stored = db.scalar(select(ProPickRun).where(ProPickRun.id == run.id))
        assert stored is not None and stored.params["weights"]


# --- One entry per issuer (share classes) -----------------------------------


def _prices(db: Session, company: Company, volume: int | None) -> None:
    from datetime import date, timedelta

    from app.models import MarketPrice

    for i in range(1, 6):
        db.add(
            MarketPrice(
                company_id=company.id,
                date=date.today() - timedelta(days=i),
                open=Decimal("10"),
                high=Decimal("11"),
                low=Decimal("9"),
                close=Decimal("10"),
                volume=volume,
            )
        )


def _good_company(db: Session, ticker: str, name: str, exchange: str = "NASDAQ") -> Company:
    company = _company(ticker)
    company.name = name
    company.exchange = exchange
    db.add(company)
    db.flush()
    _full_metrics(db, company)
    _five_good_years(db, company)
    return company


def test_share_classes_take_one_slot_and_canonical_is_highest_volume():
    with _db() as db:
        goog = _good_company(db, "GOOG", "Alphabet Inc")
        googl = _good_company(db, "GOOGL", "Alphabet Inc")
        other = _good_company(db, "OTHR", "Other Inc")
        _prices(db, goog, 21_000_000)
        _prices(db, googl, 32_000_000)
        _prices(db, other, 1_000_000)
        db.commit()
        results, stats = run_funnel(db, top_n=20)
        by_ticker = {db.get(Company, r.company_id).ticker: r for r in results}
        assert by_ticker["GOOGL"].passed is True
        assert by_ticker["GOOG"].passed is False
        assert "clase_duplicada:GOOGL" in by_ticker["GOOG"].failed_gates
        assert by_ticker["OTHR"].passed is True
        assert stats["passed_count"] == 2
        ranked_tickers = [
            db.get(Company, r.company_id).ticker for r in results if "rank" in r.metrics
        ]
        assert sorted(ranked_tickers) == ["GOOGL", "OTHR"]


def test_canonical_flips_with_volume_and_persists_single_candidate():
    with _db() as db:
        goog = _good_company(db, "GOOG", "Alphabet Inc")
        googl = _good_company(db, "GOOGL", "Alphabet Inc")
        _prices(db, goog, 50_000_000)
        _prices(db, googl, 10_000_000)
        db.commit()
        run = execute_run(db, top_n=20)
        candidates = db.scalars(
            select(ProPickCandidate).where(ProPickCandidate.run_id == run.id)
        ).all()
        by_id = {c.company_id: c for c in candidates}
        assert by_id[goog.id].passed is True and by_id[goog.id].rank == 1
        assert by_id[googl.id].passed is False and by_id[googl.id].rank is None


def test_failing_class_never_hides_a_qualifying_sibling():
    with _db() as db:
        goog = _good_company(db, "GOOG", "Alphabet Inc")
        googl = _good_company(db, "GOOGL", "Alphabet Inc")
        db.add(
            CalculatedMetric(
                company_id=googl.id, metric="roic", value=Decimal("0.01"), unit="decimal",
                period="FY2026", fiscal_year=2026, status="ok", definition_version="t",
                formula="roic", source_fact_ids=[], calculation_trace={}, confidence=Decimal("0.9"),
            )
        )
        _prices(db, goog, 1_000)
        _prices(db, googl, 9_000_000)  # higher volume but fails its own gates
        db.commit()
        results, _ = run_funnel(db)
        by_ticker = {db.get(Company, r.company_id).ticker: r for r in results}
        assert by_ticker["GOOGL"].passed is False
        assert by_ticker["GOOG"].passed is True


def test_no_volume_data_falls_back_to_lowest_id_and_zero_is_not_data():
    with _db() as db:
        first = _good_company(db, "FOX", "Fox Corp")
        second = _good_company(db, "FOXA", "Fox Corp")
        _prices(db, first, None)
        _prices(db, second, 0)
        db.commit()
        results, _ = run_funnel(db)
        by_id = {r.company_id: r for r in results}
        assert by_id[first.id].passed is True
        assert by_id[second.id].passed is False


def test_unrelated_same_name_companies_are_not_merged():
    with _db() as db:
        a = _good_company(db, "FWONA", "Formula One Group")
        b = _good_company(db, "LLYVA", "Formula One Group")
        c = _good_company(db, "GHC", "Graham Holdings Co", "NYSE")
        d = _good_company(db, "GHM", "Graham Corp", "NYSE")
        db.commit()
        results, _ = run_funnel(db)
        by_id = {r.company_id: r for r in results}
        assert all(by_id[x.id].passed for x in (a, b, c, d))


def test_name_fallback_links_unmapped_classes_with_common_root():
    with _db() as db:
        a = _good_company(db, "ABCDA", "Abcd Holdings")
        b = _good_company(db, "ABCDB", "Abcd Holdings")
        _prices(db, a, 5)
        _prices(db, b, 9)
        db.commit()
        results, _ = run_funnel(db)
        by_id = {r.company_id: r for r in results}
        assert by_id[b.id].passed is True and by_id[a.id].passed is False


def test_three_classes_form_one_group_in_any_order():
    import itertools

    from app.services.propicks_funnel_service import _group_share_classes

    base = [
        _company("ABCDA"),
        _company("ABCDB"),
        _company("ABCDC"),
        _company("OTHER"),
    ]
    for i, company in enumerate(base, start=1):
        company.id = i
        company.name = "Abcd Holdings" if company.ticker != "OTHER" else "Other Inc"
        company.exchange = "NASDAQ"
    for order in itertools.permutations(base):
        groups = _group_share_classes(list(order))
        assert set(groups) == {1, 2, 3}
        assert len(set(groups.values())) == 1


def test_three_classes_take_one_slot_in_run_funnel_and_execute_run():
    for order in ((0, 1, 2), (2, 1, 0), (1, 2, 0)):
        with _db() as db:
            made = [
                _good_company(db, t, "Abcd Holdings") for t in ("ABCDA", "ABCDB", "ABCDC")
            ]
            volumes = {"ABCDA": 5, "ABCDB": 9, "ABCDC": 7}
            for company in made:
                _prices(db, company, volumes[company.ticker])
            db.commit()
            results, stats = run_funnel(db, top_n=20)
            passing = [r for r in results if r.passed]
            assert len(passing) == 1 and stats["passed_count"] == 1
            assert db.get(Company, passing[0].company_id).ticker == "ABCDB"
            run = execute_run(db, top_n=20)
            ranked = db.scalars(
                select(ProPickCandidate).where(
                    ProPickCandidate.run_id == run.id, ProPickCandidate.rank.is_not(None)
                )
            ).all()
            assert len(ranked) == 1


def test_mapped_and_name_links_merge_into_one_component():
    from app.services.propicks_funnel_service import _group_share_classes

    a, b, c = _company("GOOG"), _company("GOOGL"), _company("GOOGX")
    for i, company in enumerate((a, b, c), start=1):
        company.id = i
        company.name = "Alphabet Inc"
        company.exchange = "NASDAQ"
    groups = _group_share_classes([c, a, b])
    assert set(groups) == {1, 2, 3} and len(set(groups.values())) == 1


def test_momentum_12m_is_persisted_in_metrics_without_changing_score():
    with _db() as db:
        good = _company("MOMO")
        db.add(good)
        db.flush()
        _full_metrics(db, good)
        _five_good_years(db, good)
        db.commit()
        base = run_funnel(db)[0][0]
        assert base.metrics["momentum_12m"] is None

        _metric(db, good, "momentum_12m", "0.25")
        db.commit()
        with_mom = run_funnel(db)[0][0]
        assert with_mom.metrics["momentum_12m"] == 0.25
        assert with_mom.score == base.score
