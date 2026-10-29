"""Supervivientes de mutmut en ``portfolio_fx_service`` (ronda 3).

Con la maquina descargada ya no hay timeouts: quedaban vivos el orden de la
tabla FX (bisect sobre una serie desordenada da otro tipo), los filtros de la
tabla por divisas y por fecha maxima, el filtro de la base en la consulta
directa e inversa y los valores de la cartera por defecto.
"""

from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, FXRate, Portfolio
from app.services.portfolio_fx_service import PortfolioFXService

SVC = PortfolioFXService()


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _rate(db, base, quote, day, rate, created=None):
    row = FXRate(base_currency=base, quote_currency=quote, rate_date=date.fromisoformat(day),
                 rate=Decimal(rate), source="ECB")
    if created:
        row.created_at = datetime.fromisoformat(created)
    db.add(row)
    db.flush()


def test_fx_table_is_sorted_by_date_even_if_rows_were_inserted_out_of_order(db):
    _rate(db, "EUR", "USD", "2026-09-20", "0.95", created="2026-09-01T00:00:00")
    _rate(db, "EUR", "USD", "2026-09-01", "0.90", created="2026-09-25T00:00:00")
    _rate(db, "EUR", "USD", "2026-09-10", "0.92", created="2026-09-24T00:00:00")
    table = SVC.fx_table(db, currencies={"USD"}, base_currency="EUR", as_of_max=date(2026, 9, 30))
    assert [day for day, _ in table[("EUR", "USD")]] == [date(2026, 9, 1), date(2026, 9, 10), date(2026, 9, 20)]
    got = SVC.rate_from_table(table, quote_currency="USD", base_currency="EUR", as_of=date(2026, 9, 15))
    assert got == Decimal("0.92")


def test_fx_table_keeps_only_requested_pairs_and_dates(db):
    _rate(db, "EUR", "USD", "2026-09-01", "0.90")
    _rate(db, "EUR", "USD", "2026-10-05", "0.80")  # despues de as_of_max
    _rate(db, "GBP", "USD", "2026-09-01", "0.75")  # base no pedida
    _rate(db, "EUR", "CHF", "2026-09-01", "1.05")  # quote no pedida
    table = SVC.fx_table(db, currencies={"USD"}, base_currency="EUR", as_of_max=date(2026, 9, 30))
    assert table == {("EUR", "USD"): [(date(2026, 9, 1), Decimal("0.9000000000"))]}


def test_direct_rate_prefers_the_latest_date_not_the_latest_insert(db):
    _rate(db, "EUR", "USD", "2026-09-20", "0.95", created="2026-09-20T00:00:00")
    _rate(db, "EUR", "USD", "2026-09-01", "0.90", created="2026-09-28T00:00:00")
    found = SVC.rate_with_provenance(db, quote_currency="USD", base_currency="EUR", as_of=date(2026, 9, 30))
    assert (found["rate"], found["rate_date"], found["direction"]) == (Decimal("0.95"), date(2026, 9, 20), "direct")


def test_inverse_rate_prefers_the_latest_date_not_the_latest_insert(db):
    _rate(db, "USD", "EUR", "2026-09-20", "1.25", created="2026-09-20T00:00:00")
    _rate(db, "USD", "EUR", "2026-09-01", "2", created="2026-09-28T00:00:00")
    found = SVC.rate_with_provenance(db, quote_currency="USD", base_currency="EUR", as_of=date(2026, 9, 30))
    assert (found["rate"], found["rate_date"], found["direction"]) == (Decimal("0.8"), date(2026, 9, 20), "inverse")


def test_direct_lookup_requires_the_base_currency_too(db):
    # Una fila GBP<-USD no es el tipo EUR<-USD aunque la quote coincida.
    _rate(db, "GBP", "USD", "2026-09-20", "0.75")
    _rate(db, "EUR", "USD", "2026-09-01", "0.90")
    assert SVC.rate(db, quote_currency="USD", base_currency="EUR", as_of=date(2026, 9, 30)) == Decimal("0.9")


def test_inverse_lookup_requires_the_quote_to_be_the_base(db):
    # Fila USD->CHF: su base coincide con la quote pedida, pero no es EUR.
    _rate(db, "USD", "CHF", "2026-09-20", "4")
    _rate(db, "USD", "EUR", "2026-09-01", "1.25")
    assert SVC.rate(db, quote_currency="USD", base_currency="EUR", as_of=date(2026, 9, 30)) == Decimal("0.8")


def test_ensure_portfolio_creates_the_default_main_eur(db):
    created = SVC.ensure_portfolio(db)
    assert (created.name, created.base_currency, created.is_default) == ("Main", "EUR", True)
    assert SVC.portfolio(db) is created
    assert SVC.ensure_portfolio(db) is created


def test_first_default_portfolio_wins(db):
    first = Portfolio(name="A", base_currency="USD", is_default=True)
    second = Portfolio(name="B", base_currency="GBP", is_default=True)
    db.add_all([first, second])
    db.flush()
    assert SVC.portfolio(db) is first
    assert SVC.base_currency(db) == "USD"


@pytest.mark.parametrize(("call", "message"), [
    (lambda db: SVC.set_base_currency(db, "EURO"), "Base currency must be a three-letter ISO currency"),
    (lambda db: SVC.upsert_rate(db, base_currency="EU", quote_currency="USD", rate_date=date(2026, 9, 1),
                                rate=Decimal("1"), source="t"), "FX currencies must use three-letter ISO codes"),
    (lambda db: SVC.upsert_rate(db, base_currency="EUR", quote_currency="EUR", rate_date=date(2026, 9, 1),
                                rate=Decimal("2"), source="t"), "Same-currency FX rate must equal 1"),
    (lambda db: SVC.upsert_rate(db, base_currency="EUR", quote_currency="USD", rate_date=date(2026, 9, 1),
                                rate=Decimal("0"), source="t"), "FX rate must be positive"),
])
def test_validation_messages_are_stable(db, call, message):
    with pytest.raises(ValueError, match=message):
        call(db)
