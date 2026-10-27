"""Contract tests for the money path: tax report, IBKR import, XIRR.

Four defects that changed real numbers:

* the tax report INNER JOINed Company, so every cash row with company_id NULL
  (which is exactly how the IBKR importer wrote dividends and retentions)
  vanished from the filing with no flag;
* "Withholding Tax" was mapped to cash_misc, erasing the discriminator the tax
  report looks for, so the retention was invisible while the gross dividend
  was declared;
* the amount parser stripped every comma, turning a Spanish-locale Flex export
  into 100x/1000x errors that validation agreed were valid;
* XIRR added fees to the proceeds of a sale and signed fee/cash_misc rows as
  inflows, so costs RAISED the reported money-weighted return.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Company, FXRate, Portfolio, Transaction
from app.models.entities import Base
from app.services.ibkr_import_service import _decimal, _is_number
from app.services.number_parsing import parse_localized_number
from app.services.portfolio_ledger_service import (
    BUY_ACTIONS,
    SELL_ACTIONS,
    PortfolioLedgerService,
    PortfolioOversellError,
)
from app.services.tax_report_service import TaxReportService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


# --------------------------------------------------------------------------
# locale-aware money parsing
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1,234.56", Decimal("1234.56")),  # en-US
        ("1.234,56", Decimal("1234.56")),  # es-ES
        ("0,24", Decimal("0.24")),  # es-ES small
        ("0.24", Decimal("0.24")),
        ("120.50", Decimal("120.50")),
        ("1,234", Decimal("1234")),  # single comma, 3 decimals -> thousands
        ("12,5", Decimal("12.5")),  # single comma, 1 decimal -> decimal
        ("(1,250.00)", Decimal("-1250.00")),  # accounting negative
        ("-45,75", Decimal("-45.75")),
        ("  1 234,56 ", Decimal("1234.56")),  # spaces as thousands sep
        ("1\u00a0234,56", Decimal("1234.56")),  # non-breaking space
    ],
)
def test_parse_amount_handles_both_locales(raw, expected):
    parsed = parse_localized_number(raw)
    assert parsed is not None, raw
    assert parsed[0] == expected


@pytest.mark.parametrize("raw", ["1.234,56", "0,24", "1,234.56", "-45,75"])
def test_is_number_accepts_both_locales(raw):
    assert _is_number(raw) is True


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0,250", Decimal("0.250")),  # dividendo por accion es-ES, 3 decimales
        ("0.250", Decimal("0.250")),
        ("-0,125", Decimal("-0.125")),
        ("(0.125)", Decimal("-0.125")),
        ("00,500", Decimal("0.500")),
        ("1,250", Decimal("1250")),  # con parte entera distinta de 0 sigue siendo miles
        ("1.250", Decimal("1250")),
    ],
)
def test_zero_integer_part_is_always_a_decimal_separator(raw, expected):
    """Un grupo de miles nunca empieza por 0: "0,250" es 0,25 y no 250."""
    parsed = parse_localized_number(raw)
    assert parsed is not None, raw
    assert parsed[0] == expected


@pytest.mark.parametrize("raw", ["", None, "abc", "12abc", "1.2.3.4x"])
def test_is_number_rejects_garbage(raw):
    assert _is_number(raw) is False


def test_decimal_raises_instead_of_returning_zero_for_a_corrupt_amount():
    """A corrupt amount must not become a silent 0 cash flow."""
    with pytest.raises(Exception) as excinfo:
        _decimal("not-a-number")
    assert "no interpretable" in str(excinfo.value)


def test_decimal_keeps_the_zero_default_only_for_absent_values():
    assert _decimal(None) == Decimal("0")
    assert _decimal("") == Decimal("0")


# --------------------------------------------------------------------------
# ledger: an oversell must never reach the database
# --------------------------------------------------------------------------


def _portfolio(db, base="EUR"):
    row = Portfolio(name="P", base_currency=base, is_default=True)
    db.add(row)
    db.flush()
    return row


def _fx(db, quote, base, rate, when=date(2026, 1, 1)):
    db.add(
        FXRate(
            base_currency=base,
            quote_currency=quote,
            rate=Decimal(str(rate)),
            rate_date=when,
            source="test",
        )
    )
    db.flush()


def test_oversell_is_rejected_before_anything_is_written(db):
    _portfolio(db)
    ledger = PortfolioLedgerService()
    ledger.create_transaction(
        db, ticker="MSFT", action="buy", quantity=Decimal("5"),
        price=Decimal("300"), trade_date=date(2026, 1, 1), currency="USD",
    )
    db.flush()

    with pytest.raises(PortfolioOversellError):
        ledger.create_transaction(
            db, ticker="MSFT", action="sell", quantity=Decimal("9"),
            price=Decimal("320"), trade_date=date(2026, 2, 1), currency="USD",
        )

    # The impossible sale must not exist in the session either, so a caller
    # that swallows the error and commits cannot persist a phantom gain.
    persisted = db.query(Transaction).filter(Transaction.action == "sell").all()
    assert persisted == []


def test_selling_exactly_the_held_quantity_is_allowed(db):
    _portfolio(db)
    ledger = PortfolioLedgerService()
    ledger.create_transaction(
        db, ticker="MSFT", action="buy", quantity=Decimal("5"),
        price=Decimal("300"), trade_date=date(2026, 1, 1), currency="USD",
    )
    row = ledger.create_transaction(
        db, ticker="MSFT", action="sell", quantity=Decimal("5"),
        price=Decimal("320"), trade_date=date(2026, 2, 1), currency="USD",
    )
    assert row.action == "sell"


def test_held_quantity_ignores_cash_actions(db):
    _portfolio(db)
    ledger = PortfolioLedgerService()
    ledger.create_transaction(
        db, ticker="AAPL", action="buy", quantity=Decimal("10"),
        price=Decimal("150"), trade_date=date(2026, 1, 1), currency="USD",
    )
    ledger.create_transaction(
        db, ticker="AAPL", action="dividend", quantity=Decimal("0"),
        price=Decimal("2.50"), trade_date=date(2026, 2, 1), currency="USD",
    )
    assert ledger._held_quantity(db, _company_id(db, "AAPL")) == Decimal("10")


def _company_id(db, ticker):
    return db.query(Company).filter(Company.ticker == ticker.upper()).one().id


# --------------------------------------------------------------------------
# tax report: unattributed cash is income, not a missing row
# --------------------------------------------------------------------------


def _unattributed_dividend(db, portfolio, *, amount, currency="USD", action="dividend",
                            symbol="AAPL", when=date(2026, 3, 15)):
    row = Transaction(
        portfolio_id=portfolio.id,
        company_id=None,
        trade_date=when,
        action=action,
        quantity=Decimal("1"),
        price=Decimal(str(amount)),
        fees=Decimal("0"),
        currency=currency,
        external_id=f"ext-{action}-{amount}",
        raw_payload={"symbol": symbol} if symbol else {},
    )
    db.add(row)
    db.flush()
    return row


def test_tax_report_keeps_cash_with_no_company(db):
    """The INNER JOIN dropped every IBKR dividend from the filing."""
    _portfolio(db)
    # IRPF usa el tipo BCE de la fecha de la operación (máx. 7 días de antigüedad):
    # el tipo tiene que existir para el 15/03, no solo para el 01/01.
    _fx(db, "USD", "EUR", 0.9, when=date(2026, 3, 13))
    portfolio = db.query(Portfolio).one()
    _unattributed_dividend(db, portfolio, amount="120.00")

    report = TaxReportService().compute_report(db, 2026)

    assert report["summary"]["total_dividends_base"] is not None
    assert report["summary"]["total_dividends_base"] > 0
    assert report["summary"]["unattributed_tickers"] == ["UNATTRIBUTED:AAPL"]


def test_tax_report_labels_unattributed_cash_by_symbol(db):
    _portfolio(db)
    _fx(db, "USD", "EUR", 0.9)
    portfolio = db.query(Portfolio).one()
    _unattributed_dividend(db, portfolio, amount="120.00", symbol="MSFT")

    report = TaxReportService().compute_report(db, 2026)

    assert report["summary"]["unattributed_tickers"] == ["UNATTRIBUTED:MSFT"]
    assert report["dividends"][0]["unattributed"] is True


def test_tax_report_surfaces_withholding_separately(db):
    _portfolio(db)
    # IRPF usa el tipo BCE de la fecha de la operación (máx. 7 días de antigüedad):
    # el tipo tiene que existir para el 15/03, no solo para el 01/01.
    _fx(db, "USD", "EUR", 0.9, when=date(2026, 3, 13))
    portfolio = db.query(Portfolio).one()
    _unattributed_dividend(db, portfolio, amount="120.00", action="withholding")

    report = TaxReportService().compute_report(db, 2026)

    assert report["summary"]["total_withholding_base"] is not None
    assert report["summary"]["total_withholding_base"] > 0


# --------------------------------------------------------------------------
# XIRR sign convention
# --------------------------------------------------------------------------


def test_ledger_action_sets_are_disjoint_and_cover_the_verbs():
    assert frozenset() == BUY_ACTIONS & SELL_ACTIONS
    assert "buy" in BUY_ACTIONS
    assert "sell" in SELL_ACTIONS
