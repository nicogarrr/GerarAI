"""PortfolioFXService contract tests.

FX conversion touches every portfolio number the user sees: rates must
resolve point-in-time (never from the future), fall back to the inverse
pair, stay None when unknown, and reject invalid quotes at write time.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, FXRate
from app.services.portfolio_fx_service import PortfolioFXService, currency_key


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def test_same_currency_is_one_without_data(db):
    assert PortfolioFXService().rate(
        db, quote_currency="eur", base_currency="EUR", as_of=date(2026, 9, 23)
    ) == Decimal("1")


def test_rate_is_point_in_time_never_from_the_future(db):
    service = PortfolioFXService()
    service.upsert_rate(db, base_currency="EUR", quote_currency="USD",
                        rate=Decimal("1.10"), rate_date=date(2026, 9, 1), source="ecb")
    service.upsert_rate(db, base_currency="EUR", quote_currency="USD",
                        rate=Decimal("9.99"), rate_date=date(2026, 12, 31), source="ecb")
    db.commit()
    # The December rate exists but is in the future relative to as_of.
    assert service.rate(
        db, quote_currency="USD", base_currency="EUR", as_of=date(2026, 9, 23)
    ) == Decimal("1.10")
    assert service.rate(
        db, quote_currency="USD", base_currency="EUR", as_of=date(2026, 8, 1)
    ) is None  # nothing stored on or before August


def test_inverse_pair_used_when_direct_missing(db):
    service = PortfolioFXService()
    service.upsert_rate(db, base_currency="EUR", quote_currency="USD",
                        rate=Decimal("2.00"), rate_date=date(2026, 9, 1), source="ecb")
    db.commit()
    assert service.rate(
        db, quote_currency="EUR", base_currency="USD", as_of=date(2026, 9, 23)
    ) == Decimal("0.5")


def test_rate_from_table_replicates_point_in_time_semantics(db):
    service = PortfolioFXService()
    service.upsert_rate(db, base_currency="EUR", quote_currency="USD",
                        rate=Decimal("1.10"), rate_date=date(2026, 9, 1), source="ecb")
    service.upsert_rate(db, base_currency="EUR", quote_currency="USD",
                        rate=Decimal("9.99"), rate_date=date(2026, 12, 31), source="ecb")
    db.commit()
    table = service.fx_table(
        db, currencies={"USD"}, base_currency="EUR", as_of_max=date(2026, 9, 23)
    )
    # The December rate never even enters the table (lookahead filtered).
    assert service.rate_from_table(
        table, quote_currency="USD", base_currency="EUR", as_of=date(2026, 9, 23)
    ) == Decimal("1.10")
    assert service.rate_from_table(
        table, quote_currency="USD", base_currency="EUR", as_of=date(2026, 8, 1)
    ) is None
    assert service.rate_from_table(
        table, quote_currency="EUR", base_currency="USD", as_of=date(2026, 9, 23)
    ) == pytest.approx(Decimal("1") / Decimal("1.10"))
    assert service.rate_from_table(
        table, quote_currency="EUR", base_currency="EUR", as_of=date(2026, 9, 23)
    ) == Decimal("1")


def test_upsert_rate_validates_and_updates_in_place(db):
    service = PortfolioFXService()
    with pytest.raises(ValueError, match="three-letter ISO"):
        service.upsert_rate(db, base_currency="EURO", quote_currency="USD",
                            rate=Decimal("1"), rate_date=date(2026, 9, 1), source="x")
    with pytest.raises(ValueError, match="must be positive"):
        service.upsert_rate(db, base_currency="EUR", quote_currency="USD",
                            rate=Decimal("0"), rate_date=date(2026, 9, 1), source="x")
    with pytest.raises(ValueError, match="must equal 1"):
        service.upsert_rate(db, base_currency="EUR", quote_currency="EUR",
                            rate=Decimal("1.1"), rate_date=date(2026, 9, 1), source="x")

    first = service.upsert_rate(db, base_currency="EUR", quote_currency="USD",
                                rate=Decimal("1.10"), rate_date=date(2026, 9, 1), source="ecb")
    second = service.upsert_rate(db, base_currency="EUR", quote_currency="USD",
                                 rate=Decimal("1.12"), rate_date=date(2026, 9, 1), source="manual")
    assert first.id == second.id
    assert db.query(FXRate).count() == 1
    assert db.get(FXRate, first.id).rate == Decimal("1.12")
    assert db.get(FXRate, first.id).source == "manual"


@pytest.mark.parametrize("quote,base,expected", [
    ("GBX", "EUR", "0.0117"), ("GBp", "EUR", "0.0117"),
    ("GBP", "EUR", "1.17"), ("GBX", "GBP", "0.01"),
    ("GBP", "GBX", "100"), ("GBX", "GBX", "1"),
])
def test_explicit_subunit_effective_rates_all_paths(db, quote, base, expected):
    from app.services.tax_report_service import _rate_not_older_than

    service = PortfolioFXService()
    day = date(2026, 3, 10)
    service.upsert_rate(db, base_currency="EUR", quote_currency="GBP",
                        rate=Decimal("1.17"), rate_date=day, source="test")
    db.commit()
    expected = Decimal(expected)
    table = service.fx_table(db, currencies={quote}, base_currency=base, as_of_max=day)
    assert service.rate(db, quote_currency=quote, base_currency=base, as_of=day) == expected
    assert service.rate_from_table(table, quote_currency=quote, base_currency=base, as_of=day) == expected
    assert service.rates_for(db, quote_currencies={quote}, base_currency=base, as_of=day)[currency_key(quote)] == expected
    assert _rate_not_older_than(table, quote_currency=quote, base_currency=base,
                               as_of=day, max_age_days=7) == expected
    provenance = service.rate_with_provenance(db, quote_currency=quote, base_currency=base, as_of=day)
    assert provenance["rate"] == expected


def test_subunit_does_not_create_missing_fx_or_reuse_future_rate(db):
    from app.services.tax_report_service import _rate_not_older_than

    service = PortfolioFXService()
    day = date(2026, 3, 10)
    assert service.rate(db, quote_currency="GBX", base_currency="EUR", as_of=day) is None
    service.upsert_rate(db, base_currency="EUR", quote_currency="GBP",
                        rate=Decimal("1.17"), rate_date=day, source="test")
    db.commit()
    table = service.fx_table(db, currencies={"GBX"}, base_currency="EUR", as_of_max=date(2026, 3, 31))
    assert service.rate_from_table(table, quote_currency="GBX", base_currency="EUR",
                                   as_of=date(2026, 3, 9)) is None
    assert _rate_not_older_than(table, quote_currency="GBX", base_currency="EUR",
                               as_of=date(2026, 3, 18), max_age_days=7) is None
    # Total 2325 pence = 23.25 pounds, not a per-share dividend assertion.
    assert Decimal("2325") * service.rate_from_table(
        table, quote_currency="GBX", base_currency="EUR", as_of=day
    ) == Decimal("27.2025")


def test_tax_dividend_total_in_pence_uses_pound_fx(db):
    from app.models import Transaction
    from app.services.portfolio_ledger_service import PortfolioLedgerService
    from app.services.tax_report_service import TaxReportService

    ledger = PortfolioLedgerService()
    company = ledger.ensure_company(db, "SHEL.L")
    portfolio = PortfolioFXService().ensure_portfolio(db)
    day = date(2026, 3, 10)
    db.add(Transaction(portfolio_id=portfolio.id, company_id=company.id,
                       trade_date=day, action="dividend", quantity=1,
                       price=Decimal("2325"), currency="GBX"))
    PortfolioFXService().upsert_rate(db, base_currency="EUR", quote_currency="GBP",
                                   rate=Decimal("1.17"), rate_date=day, source="test")
    db.commit()
    report = TaxReportService().compute_report(db, 2026, include_filing=False)
    assert report["dividends"][0]["dividends_base"] == pytest.approx(27.20)
    assert report["summary"]["missing_fx"] == []


@pytest.mark.parametrize("units", [["GBP", "GBp"], ["GBp", "GBP"], ["GBX", "GBP", "GBp"]])
def test_batch_major_and_minor_units_do_not_collide(db, units):
    service = PortfolioFXService()
    day = date(2026, 3, 10)
    service.upsert_rate(db, base_currency="EUR", quote_currency="GBP",
                        rate=Decimal("1.17"), rate_date=day, source="test")
    db.commit()
    rates = service.rates_for(db, quote_currencies=units, base_currency="EUR", as_of=day)
    assert rates[currency_key("GBP")] == Decimal("1.17")
    assert rates[currency_key("GBp")] == Decimal("0.0117")
    assert currency_key("GBp") == currency_key("GBX")
    assert currency_key("GBp") != currency_key("GBP")


def test_snapshot_mixed_pound_and_pence_cash(db):
    from app.models import CashBalance
    from app.services.portfolio_snapshot_service import PortfolioSnapshotService

    day = date(2026, 3, 10)
    PortfolioFXService().ensure_portfolio(db)
    PortfolioFXService().upsert_rate(db, base_currency="EUR", quote_currency="GBP",
                                   rate=Decimal("1.17"), rate_date=day, source="test")
    db.add_all([CashBalance(currency="GBP", balance=100, as_of=day), CashBalance(currency="GBp", balance=100, as_of=day)])
    db.commit()
    snapshot = PortfolioSnapshotService().capture(db, as_of=day, source="test")
    assert snapshot.cash_value_base == Decimal("118.17")


def test_currency_key_rejects_missing_currency_instead_of_returning_none():
    import pytest

    from app.services.portfolio_fx_service import currency_key
    with pytest.raises(ValueError, match="Divisa no registrada"):
        currency_key("")
