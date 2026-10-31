"""Dividend yield is None when no record matches the position's currency.

``portfolio_yields`` gated the yield on ``records`` (every ingested row) while
the TTM sum only used the records whose currency matches the position price.
With every record skipped for a currency mismatch, TTM was 0 and the position
was published with ``dividend_yield: 0.0`` - a fabricated fact that reads as
"this position pays nothing" and drags the aggregate down. The weight also
fell back to the NATIVE value, so ``total_value`` summed EUR and USD.

Posiciones sin valor en divisa base no tienen peso honesto: se excluyen del
agregado y se reportan en cobertura.
"""

import asyncio
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, DividendRecord, Portfolio, Position
from app.services.dividend_ingestion_service import DividendIngestionService


class _NoProvider:
    async def dividends(self, ticker: str):  # pragma: no cover - never called
        return []


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _company(db: Session, ticker: str, currency: str = "USD") -> Company:
    company = Company(
        ticker=ticker, name=ticker, exchange="NASDAQ", currency=currency,
        sector="Tech", industry="Tech", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _position(
    db: Session,
    company: Company,
    *,
    price: str,
    currency: str,
    value_base: str | None,
) -> Position:
    db.add(Portfolio(name="p", base_currency="EUR", is_default=True))
    db.commit()
    position = Position(
        company_id=company.id,
        quantity=Decimal("10"),
        average_cost=Decimal("150"),
        market_price=Decimal(price),
        # Native value deliberately large: weighting on it is what mixed
        # currencies into the aggregate total.
        market_value=Decimal("999999"),
        market_value_base=None if value_base is None else Decimal(value_base),
        as_of=date.today(),
        currency=currency,
    )
    db.add(position)
    db.commit()
    return position


def _dividend(db: Session, company: Company, amount: str, currency: str) -> None:
    db.add(
        DividendRecord(
            company_id=company.id,
            ex_date=date.today(),
            amount=Decimal(amount),
            currency=currency,
            source="fmp",
        )
    )
    db.commit()


def _yields(db: Session) -> dict:
    return DividendIngestionService(fmp=_NoProvider(), yahoo=_NoProvider()).portfolio_yields(db)


def test_full_currency_mismatch_yields_none_never_zero(db: Session):
    company = _company(db, "MIS")  # USD company
    # Position priced in EUR, dividend declared in USD: nothing usable.
    _position(db, company, price="200.00", currency="EUR", value_base="1800.00")
    _dividend(db, company, "0.50", "USD")

    result = _yields(db)
    position = result["positions"][0]
    assert position["skipped_currency_mismatch"] == 1
    assert position["matching_currency_records_12m"] == 0
    assert position["dividend_yield"] is None
    assert position["ttm_dividend_per_share"] is None
    # The position has no usable dividend data, so coverage must say so.
    assert result["coverage"]["positions_with_dividend_data"] == 0
    assert result["coverage"]["percent"] == 0.0
    assert result["provenance"]["coverage"] == "unavailable"
    # Nothing to weight: no fabricated aggregate either.
    assert result["portfolio_yield"] is None


def test_partial_currency_mismatch_yields_only_the_matching_records(db: Session):
    company = _company(db, "MIX")
    _position(db, company, price="200.00", currency="USD", value_base="1800.00")
    _dividend(db, company, "0.50", "USD")
    _dividend(db, company, "0.75", "GBP")

    result = _yields(db)
    position = result["positions"][0]
    assert position["skipped_currency_mismatch"] == 1
    assert position["records_12m"] == 2
    assert position["ttm_dividend_per_share"] == pytest.approx(0.5)
    assert position["dividend_yield"] == pytest.approx(0.0025)
    assert result["portfolio_yield"] == pytest.approx(0.0025)


def test_portfolio_yield_never_sums_two_currencies(db: Session):
    valued = _company(db, "EURB")
    _position(db, valued, price="100.00", currency="EUR", value_base="1000.00")
    _dividend(db, valued, "10.00", "EUR")

    # Same book, but the second position has no base-currency value: its
    # native amount is 999999 in another currency and must not be added.
    unvalued = _company(db, "USDB")
    _position(db, unvalued, price="100.00", currency="USD", value_base=None)
    _dividend(db, unvalued, "5.00", "USD")

    result = _yields(db)
    by_ticker = {row["ticker"]: row for row in result["positions"]}
    assert by_ticker["EURB"]["dividend_yield"] == pytest.approx(0.10)
    assert by_ticker["USDB"]["dividend_yield"] == pytest.approx(0.05)
    # 10% of 1000 / 1000 - not diluted (or inflated) by the unvalued position.
    assert result["portfolio_yield"] == pytest.approx(0.10)
    assert result["coverage"]["positions"] == 2
    assert result["coverage"]["positions_missing_base_value"] == ["USDB"]


def test_position_without_dividend_data_does_not_dilute_the_aggregate(db: Session):
    valued = _company(db, "PAYE")
    _position(db, valued, price="100.00", currency="EUR", value_base="1000.00")
    _dividend(db, valued, "10.00", "EUR")

    # Misma cartera valorada, pero la segunda posicion no tiene registros de
    # dividendo: su yield es desconocido (None), no 0 %. Si su valor entra en
    # el denominador, el agregado se diluye como si no pagara nada.
    silent = _company(db, "QUIET")
    _position(db, silent, price="100.00", currency="EUR", value_base="1000.00")

    result = _yields(db)
    by_ticker = {row["ticker"]: row for row in result["positions"]}
    assert by_ticker["QUIET"]["dividend_yield"] is None
    # 10% sobre el valor CUBIERTO (1000), no 5% sobre el valor total (2000).
    assert result["portfolio_yield"] == pytest.approx(0.10)


def test_no_position_has_a_base_value_yields_none_not_zero(db: Session):
    company = _company(db, "NOFX")
    _position(db, company, price="100.00", currency="USD", value_base=None)
    _dividend(db, company, "5.00", "USD")

    result = _yields(db)
    # The per-position yield is real (same currency); the aggregate is not,
    # because there is no honest denominator.
    assert result["positions"][0]["dividend_yield"] == pytest.approx(0.05)
    assert result["portfolio_yield"] is None
    assert result["coverage"]["positions_missing_base_value"] == ["NOFX"]


def test_existing_records_without_prices_stay_unknown(db: Session):
    """No regression on the plain no-data case: no records, no yield."""
    company = _company(db, "BARE")
    _position(db, company, price="400.00", currency="USD", value_base="3600.00")

    result = _yields(db)
    position = result["positions"][0]
    assert position["dividend_yield"] is None
    assert position["ttm_dividend_per_share"] is None
    assert result["coverage"]["positions_with_dividend_data"] == 0
    assert result["portfolio_yield"] is None


def test_sync_is_untouched_by_the_yield_gate(db: Session):
    """Sanity: the ingest path still runs with the same provider contract."""
    company = _company(db, "SYNC")
    result = asyncio.run(
        DividendIngestionService(fmp=_NoProvider(), yahoo=_NoProvider()).sync_company(
            db, ticker="SYNC"
        )
    )
    assert result["status"] == "ok" and result["inserted"] == 0
    assert company.id is not None


def test_ttm_yield_excludes_declared_future_and_year_old_ex_dates(db: Session):
    """TTM = (hoy - 1 año, hoy]: 4 pagos trimestrales de 0,25 sobre precio 100 = 1 %.

    Un dividendo ya declarado con ex_date futuro y el de hace exactamente un
    año no son de los ultimos 12 meses: con ellos salian 6 pagos (1,5 %).
    """
    company = _company(db, "QTR")
    _position(db, company, price="100.00", currency="USD", value_base="900.00")
    today = date.today()
    offsets = [-30, -120, -210, -300, 20]  # 4 pasados + 1 declarado futuro
    ex_dates = [today + timedelta(days=offset) for offset in offsets]
    try:
        ex_dates.append(today.replace(year=today.year - 1))
    except ValueError:  # 29 de febrero
        ex_dates.append(today.replace(year=today.year - 1, day=28))
    for ex_date in ex_dates:
        db.add(
            DividendRecord(
                company_id=company.id,
                ex_date=ex_date,
                amount=Decimal("0.25"),
                currency="USD",
                source="fmp",
            )
        )
    db.commit()

    position = _yields(db)["positions"][0]
    assert position["records_12m"] == 4
    assert position["ttm_dividend_per_share"] == pytest.approx(1.0)
    assert position["dividend_yield"] == pytest.approx(0.01)
