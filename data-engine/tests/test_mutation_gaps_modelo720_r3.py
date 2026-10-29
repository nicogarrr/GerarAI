"""Supervivientes de mutacion en ``tax_modelo720_service`` (ronda 3): valores y cuentas.

Saldos y posiciones actuales sin snapshot, snapshots sin provenance, fecha
del precio en el limite de antiguedad, posicion de valor positivo pequeno y
cuentas a 0 el 31/12 con saldo medio del 4T. Fija el comportamiento ACTUAL;
no cambia umbrales ni criterio fiscal.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import (
    CashBalance,
    CashDailySnapshot,
    Company,
    Portfolio,
    PortfolioDailySnapshot,
    Position,
    PositionDailySnapshot,
    Tenant,
)
from app.services.tax_modelo720_service import Modelo720Service

YEAR_END = date(2025, 12, 31)


def _new_db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


@pytest.fixture()
def db():
    with _new_db() as session:
        yield session


def _seed(db, custody=None):
    tenant = Tenant(external_id="m720-r3", name="M720 r3")
    db.add(tenant)
    db.flush()
    if custody:
        tenant.metadata_ = {"tax_declarant": {"custody": custody}}
    portfolio = Portfolio(tenant_id=tenant.id, name="Main", base_currency="EUR", is_default=True)
    db.add(portfolio)
    db.flush()
    return tenant, portfolio


def _company(db, ticker, isin=None):
    company = Company(ticker=ticker, name=ticker, exchange="X", currency="USD", sector="S",
                      industry="I", company_type="imported_holding", valuation_model="unassigned",
                      isin=isin)
    db.add(company)
    db.flush()
    return company


def _parent(db, tenant, portfolio, day, metadata=None):
    snap = db.query(PortfolioDailySnapshot).filter_by(portfolio_id=portfolio.id, snapshot_date=day).first()
    if snap is None:
        snap = PortfolioDailySnapshot(
            tenant_id=tenant.id, portfolio_id=portfolio.id, snapshot_date=day, base_currency="EUR",
            positions_value_base=Decimal("0"), cash_value_base=Decimal("0"),
            total_value_base=Decimal("0"),
            metadata_=metadata if metadata is not None else {"missing_pricing": []},
        )
        db.add(snap)
        db.flush()
    return snap


def _position_snapshot(db, tenant, portfolio, company, value_base, day=YEAR_END, metadata=None):
    snap = _parent(db, tenant, portfolio, day, metadata)
    db.add(PositionDailySnapshot(
        tenant_id=tenant.id, portfolio_snapshot_id=snap.id, portfolio_id=portfolio.id,
        company_id=company.id, snapshot_date=day, quantity=Decimal("10"),
        market_price_native=Decimal("1"), currency="USD", fx_rate=Decimal("1"),
        market_value_native=Decimal(str(value_base)), market_value_base=Decimal(str(value_base)),
    ))
    db.flush()


def _cash_snapshot(db, tenant, portfolio, currency, balance, fx, day=YEAR_END):
    snap = _parent(db, tenant, portfolio, day)
    db.add(CashDailySnapshot(
        tenant_id=tenant.id, portfolio_snapshot_id=snap.id, portfolio_id=portfolio.id,
        snapshot_date=day, currency=currency, balance_native=Decimal(str(balance)),
        fx_rate=Decimal(str(fx)) if fx is not None else None,
    ))
    db.flush()


def _position(db, tenant, portfolio, company, quantity):
    db.add(Position(tenant_id=tenant.id, company_id=company.id, portfolio_id=portfolio.id,
                    quantity=Decimal(quantity), average_cost=Decimal("1"),
                    market_value=Decimal("1"), base_currency="EUR", source="ibkr_flex"))
    db.flush()


def _balance(db, tenant, currency, amount):
    db.add(CashBalance(tenant_id=tenant.id, currency=currency, balance=Decimal(amount),
                       source="ibkr_flex"))
    db.flush()


def _check(db):
    return Modelo720Service().check_thresholds(db, 2025)


def test_current_cash_balance_without_snapshot_is_listed_only_when_positive(db):
    tenant, portfolio = _seed(db, custody={"cash:EUR": "IE"})
    _cash_snapshot(db, tenant, portfolio, "EUR", 1000, 1)
    _balance(db, tenant, "EUR", "500")   # cubierta por el snapshot
    _balance(db, tenant, "USD", "0")
    _balance(db, tenant, "GBP", "-5")
    _balance(db, tenant, "CHF", "0.5")
    _balance(db, tenant, "SEK", "300")
    result = _check(db)
    cash_unvalued = [u for u in result["unvalued"] if u["ticker"].startswith("cash-")]
    assert sorted(u["ticker"] for u in cash_unvalued) == ["cash-CHF", "cash-SEK"]
    assert all(u["snapshot_date"] is None for u in cash_unvalued)
    assert all("Saldo actual sin snapshot" in u["reason"] for u in cash_unvalued)
    assert result["categories"]["cuentas"]["status"] == "desconocido"


def test_current_position_without_snapshot_needs_a_non_zero_quantity(db):
    tenant, portfolio = _seed(db, custody={"AAA": "IE"})
    covered, empty, one = _company(db, "AAA"), _company(db, "BBB"), _company(db, "CCC")
    _position_snapshot(db, tenant, portfolio, covered, 1000)
    _position(db, tenant, portfolio, covered, "10")
    _position(db, tenant, portfolio, empty, "0")
    _position(db, tenant, portfolio, one, "1")
    result = _check(db)
    assert [u["ticker"] for u in result["unvalued"]] == ["CCC"]
    assert result["categories"]["valores"]["status"] == "desconocido"


def test_snapshot_without_provenance_never_enters_the_total(db):
    tenant, portfolio = _seed(db, custody={"AAA": "IE"})
    company = _company(db, "AAA")
    _position_snapshot(db, tenant, portfolio, company, 60000, metadata={})
    valores = _check(db)["categories"]["valores"]
    assert valores["total_base"] == 0.0
    assert valores["positions"] == []
    assert valores["exceeds"] is None


def test_small_positive_position_is_counted_not_short(db):
    tenant, portfolio = _seed(db, custody={"AAA": "IE"})
    company = _company(db, "AAA")
    _position_snapshot(db, tenant, portfolio, company, "0.5")
    result = _check(db)
    assert result["short_positions"] == []
    assert result["categories"]["valores"]["total_base"] == pytest.approx(0.5)


@pytest.mark.parametrize(("valuation_date", "counted"), [
    ("2025-12-31", True),
    ("2025-12-21", True),    # 10 dias: el limite aun vale
    ("2025-12-20", False),   # 11 dias: demasiado antigua
    ("2026-01-02", False),   # posterior al cierre
    ("no-es-fecha", False),
])
def test_price_date_of_the_capture_at_the_age_limit(valuation_date, counted):
    with _new_db() as db:
        tenant, portfolio = _seed(db, custody={"AAA": "IE"})
        company = _company(db, "AAA")
        _position_snapshot(db, tenant, portfolio, company, 1000, metadata={
            "missing_pricing": [
                {"company_id": company.id, "valuation_date": valuation_date},
                {"company_id": None, "valuation_date": "2020-01-01"},
            ],
        })
        result = _check(db)
        assert (result["categories"]["valores"]["total_base"] == 1000.0) is counted
        assert bool(result["stale_snapshots"]) is (not counted)


def _zero_account(db, tenant, portfolio, currency, q4_balance):
    # Capturas semanales (sin huecos de mas de 7 dias) y saldo 0 el 31/12.
    day = date(2025, 9, 30)
    while day < YEAR_END:
        _cash_snapshot(db, tenant, portfolio, currency, q4_balance, "0.9", day=day)
        day += timedelta(days=7)
    _cash_snapshot(db, tenant, portfolio, currency, 0, "0.9")


def _q4_total(currencies):
    with _new_db() as db:
        tenant, portfolio = _seed(db, custody={f"cash:{c}": "IE" for c, _ in currencies})
        for currency, balance in currencies:
            _zero_account(db, tenant, portfolio, currency, balance)
        return _check(db)["categories"]["cuentas"]


def test_q4_average_of_zero_accounts_is_added_across_accounts():
    usd = _q4_total([("USD", 10000)])
    gbp = _q4_total([("GBP", 20000)])
    both = _q4_total([("USD", 10000), ("GBP", 20000)])
    assert usd["average_q4_missing"] is False
    assert usd["average_q4_total_base"] > 0
    assert both["average_q4_missing"] is False
    assert both["average_q4_total_base"] == pytest.approx(
        usd["average_q4_total_base"] + gbp["average_q4_total_base"], abs=0.02)


def test_zero_account_without_q4_history_makes_the_average_unknown(db):
    tenant, portfolio = _seed(db, custody={"cash:USD": "IE"})
    _cash_snapshot(db, tenant, portfolio, "USD", 0, "0.9")
    cuentas = _check(db)["categories"]["cuentas"]
    assert cuentas["average_q4_missing"] is True
    assert any("cash-USD" in reason for reason in cuentas["reasons"])


def test_only_a_short_position_is_below_not_unknown(db):
    tenant, portfolio = _seed(db, custody={"AAA": "IE"})
    company = _company(db, "AAA")
    _position_snapshot(db, tenant, portfolio, company, -500)
    valores = _check(db)["categories"]["valores"]
    assert valores["total_base"] == 0.0
    assert valores["status"] == "por_debajo"
    assert valores["exceeds"] is False


def test_stale_snapshot_reason_names_the_stale_items(db):
    tenant, portfolio = _seed(db, custody={"AAA": "IE", "cash:USD": "IE"})
    company = _company(db, "AAA")
    _position_snapshot(db, tenant, portfolio, company, 1000, day=date(2025, 11, 1))
    _cash_snapshot(db, tenant, portfolio, "USD", 1000, "0.9", day=date(2025, 11, 1))
    result = _check(db)
    valores, cuentas = result["categories"]["valores"], result["categories"]["cuentas"]
    assert valores["status"] == cuentas["status"] == "desconocido"
    assert any("snapshot demasiado antiguo (AAA)" in r for r in valores["reasons"])
    assert any("snapshot demasiado antiguo (cash-USD)" in r for r in cuentas["reasons"])


def test_unknown_q4_average_reports_no_average_figures(db):
    tenant, portfolio = _seed(db, custody={"cash:USD": "IE"})
    _cash_snapshot(db, tenant, portfolio, "USD", 0, "0.9")
    cuentas = _check(db)["categories"]["cuentas"]
    assert cuentas["average_q4_total_base"] is None
    assert cuentas["average_q4_estimate"] is None
    known = _q4_total([("USD", 10000)])
    assert known["average_q4_estimate"] is True
    assert known["average_q4_method"] != cuentas["average_q4_method"]


def test_non_eur_portfolio_reason_names_the_portfolio(db):
    tenant, portfolio = _seed(db, custody={"cash:EUR": "IE"})
    db.add(Portfolio(tenant_id=tenant.id, name="Dolares", base_currency="USD"))
    db.flush()
    _cash_snapshot(db, tenant, portfolio, "EUR", 1000, 1)
    cuentas = _check(db)["categories"]["cuentas"]
    assert any("Dolares (USD)" in r for r in cuentas["reasons"])
