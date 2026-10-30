"""HistoricalValuationService contract tests.

Historical multiples are only meaningful point-in-time: future data must
stay out of the series, missing inputs must stay visibly missing, and every multiple must
be traceable to the stored rows that produced it.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, FinancialFact, MarketPrice
from app.services.historical_valuation_service import HistoricalValuationService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db: Session) -> Company:
    company = Company(
        ticker="AAPL", name="Apple", exchange="NASDAQ", currency="USD",
        sector="Tech", industry="Tech", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _fact(db, company, *, metric, fiscal_year, value, quarter=None):
    fact = FinancialFact(
        company_id=company.id, metric=metric, value=Decimal(str(value)), unit="USD",
        period=f"{fiscal_year}:FY", fiscal_year=fiscal_year, fiscal_quarter=quarter,
        source_type="SEC", is_reported=True, confidence=Decimal("0.95"),
    )
    db.add(fact)
    db.commit()
    return fact


def test_series_math_and_source_ids(db):
    company = _company(db)
    price = MarketPrice(
        company_id=company.id, date=date(2024, 12, 31),
        open=Decimal("190"), high=Decimal("200"), low=Decimal("189"),
        close=Decimal("200"), adj_close=Decimal("200"), source="Finnhub",
    )
    db.add(price)
    db.commit()
    eps = _fact(db, company, metric="eps", fiscal_year=2024, value="10")
    shares = _fact(db, company, metric="shares_diluted", fiscal_year=2024, value="100")
    fcf = _fact(db, company, metric="free_cash_flow", fiscal_year=2024, value="1000")
    revenue = _fact(db, company, metric="revenue", fiscal_year=2024, value="4000")
    _fact(db, company, metric="total_debt", fiscal_year=2024, value="300")
    _fact(db, company, metric="cash_and_equivalents", fiscal_year=2024, value="100")

    result = HistoricalValuationService().build(db, company, as_of=date(2026, 9, 23))
    assert result["ticker"] == "AAPL"
    point = next(p for p in result["series"] if p["year"] == 2024)
    # market cap 200*100=20000; EV = 20000 + 300 - 100 = 20200
    assert point["pe"] == pytest.approx(Decimal("20"))
    assert point["fcf_per_share"] == pytest.approx(Decimal("10"))
    assert point["revenue_per_share"] == pytest.approx(Decimal("40"))
    assert point["ev_to_fcf"] == pytest.approx(Decimal("20.2"))
    assert point["ev_to_revenue"] == pytest.approx(Decimal("5.05"))
    assert point["source_ids"]["market_price"] == price.id
    assert point["source_ids"]["eps"] == eps.id
    assert result["coverage"]["complete_valuation_points"] == 1
    assert result["statistics"]["pe"]["median"] == pytest.approx(Decimal("20"))


def test_future_data_is_excluded_not_raised(db):
    company = _company(db)
    db.add(
        MarketPrice(
            company_id=company.id, date=date(2026, 12, 31),
            open=Decimal("1"), high=Decimal("1"), low=Decimal("1"),
            close=Decimal("1"), adj_close=Decimal("1"), source="Finnhub",
        )
    )
    db.commit()
    _fact(db, company, metric="eps", fiscal_year=2027, value="1")
    # Revision GerarAI A2: un replay filtra lo posterior a as_of en vez de
    # abortar; ni el precio de dic-2026 ni el FY2027 entran en la serie.
    result = HistoricalValuationService().build(db, company, as_of=date(2026, 9, 23))
    assert result["series"] == []


def test_missing_inputs_stay_none_and_are_reported(db):
    company = _company(db)
    db.add(
        MarketPrice(
            company_id=company.id, date=date(2024, 12, 31),
            open=Decimal("1"), high=Decimal("1"), low=Decimal("1"),
            close=Decimal("200"), adj_close=Decimal("200"), source="Finnhub",
        )
    )
    db.commit()
    # Price only, no fundamentals: multiples are None, never fabricated.
    result = HistoricalValuationService().build(db, company, as_of=date(2026, 9, 23))
    point = result["series"][0]
    assert point["pe"] is None
    assert point["ev_to_fcf"] is None
    assert result["coverage"]["complete_valuation_points"] == 0
    assert 2024 in result["coverage"]["missing_by_metric"]["pe"]
    assert result["statistics"]["pe"]["median"] is None


def test_quarterly_facts_excluded_from_annual_series(db):
    company = _company(db)
    _fact(db, company, metric="eps", fiscal_year=2024, value="99", quarter="Q1")
    result = HistoricalValuationService().build(db, company, as_of=date(2026, 9, 23))
    # A lone quarterly fact never enters the annual series.
    assert result["series"] == []


def test_percentile_interpolates_between_points():
    service = HistoricalValuationService()
    values = [Decimal("10"), Decimal("20"), Decimal("30")]
    assert service._percentile(values, Decimal("0.5")) == Decimal("20")
    assert service._percentile(values, Decimal("0.25")) == pytest.approx(Decimal("15"))
    assert service._percentile([Decimal("7")], Decimal("0.9")) == Decimal("7")


def test_negative_earnings_or_fcf_multiples_are_nd_and_stay_out_of_statistics(db):
    """P/E y EV/FCF con denominador negativo son N/D, no un múltiplo negativo.
    Esperado a mano (sin deuda ni caja, 10 acciones):
      2022: precio 200, EPS 10  -> P/E 20; FCF 100 -> EV/FCF 2000/100 = 20
      2023: precio 100, EPS -5  -> N/D;    FCF -50 -> N/D
      2024: precio 80,  EPS 8   -> P/E 10; FCF 80  -> EV/FCF 800/80 = 10
    Mediana P/E = (20 + 10) / 2 = 15 (antes entraba -20 y salía 10)."""
    company = _company(db)
    for year, close, eps, fcf in ((2022, 200, 10, 100), (2023, 100, -5, -50), (2024, 80, 8, 80)):
        db.add(MarketPrice(
            company_id=company.id, date=date(year, 12, 30), open=Decimal(close),
            high=Decimal(close), low=Decimal(close), close=Decimal(close),
            adj_close=Decimal(close), source="Finnhub",
        ))
        db.commit()
        _fact(db, company, metric="eps", fiscal_year=year, value=eps)
        _fact(db, company, metric="shares_diluted", fiscal_year=year, value=10)
        _fact(db, company, metric="free_cash_flow", fiscal_year=year, value=fcf)
        _fact(db, company, metric="revenue", fiscal_year=year, value=1000)
        _fact(db, company, metric="total_debt", fiscal_year=year, value=0)
        _fact(db, company, metric="cash_and_equivalents", fiscal_year=year, value=0)

    result = HistoricalValuationService().build(db, company, as_of=date(2026, 9, 23))
    points = {p["year"]: p for p in result["series"]}
    assert points[2023]["pe"] is None
    assert points[2023]["ev_to_fcf"] is None
    assert points[2023]["fcf_per_share"] == pytest.approx(Decimal("-5"))
    assert points[2022]["pe"] == pytest.approx(Decimal("20"))
    assert points[2024]["ev_to_fcf"] == pytest.approx(Decimal("10"))
    assert result["statistics"]["pe"]["median"] == pytest.approx(Decimal("15"))
    assert result["statistics"]["ev_to_fcf"]["median"] == pytest.approx(Decimal("15"))
    assert 2023 in result["coverage"]["missing_by_metric"]["pe"]


def _adr_seed(db, tags):
    company = _company(db)
    company.factor_tags = tags
    db.add(MarketPrice(
        company_id=company.id, date=date(2024, 12, 31),
        open=Decimal("200"), high=Decimal("200"), low=Decimal("200"),
        close=Decimal("200"), adj_close=Decimal("200"), source="Finnhub",
    ))
    db.commit()
    for metric, value in (("eps", "10"), ("shares_diluted", "100"), ("free_cash_flow", "1000"),
                          ("revenue", "4000"), ("total_debt", "300"), ("cash_and_equivalents", "100")):
        _fact(db, company, metric=metric, fiscal_year=2024, value=value)
    return company


def test_adr_multiples_use_price_per_ordinary_share(db):
    """ADR 2:1 (adr:2); hechos por ordinaria. Precio por ordinaria 200 / 2 = 100.

    PER = 100 / 10 = 10 (en main 20); cap = 100 x 100 = 10.000;
    EV = 10.000 + 300 − 100 = 10.200 -> EV/FCF 10,2 y EV/ventas 2,55.
    El precio mostrado sigue siendo el del ADR (200).
    """
    company = _adr_seed(db, ["adr:2"])
    result = HistoricalValuationService().build(db, company, as_of=date(2026, 9, 23))
    point = next(p for p in result["series"] if p["year"] == 2024)
    assert point["price"] == pytest.approx(Decimal("200"))
    assert point["pe"] == pytest.approx(Decimal("10"))
    assert point["ev_to_fcf"] == pytest.approx(Decimal("10.2"))
    assert point["ev_to_revenue"] == pytest.approx(Decimal("2.55"))
    assert result["adr_ratio"] == 2


def test_adr_tag_without_ratio_has_no_multiples(db):
    company = _adr_seed(db, ["adr"])
    result = HistoricalValuationService().build(db, company, as_of=date(2026, 9, 23))
    point = next(p for p in result["series"] if p["year"] == 2024)
    assert point["pe"] is None and point["ev_to_fcf"] is None and point["ev_to_revenue"] is None
