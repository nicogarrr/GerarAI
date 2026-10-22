"""rate() y rate_with_provenance() comparten una sola seleccion."""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, FXRate
from app.services.portfolio_fx_service import PortfolioFXService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _add(db, base, quote, rate, on, source="s"):
    db.add(FXRate(base_currency=base, quote_currency=quote,
                  rate=Decimal(rate), rate_date=on, source=source))
    db.commit()


def _both(db, quote, base, as_of):
    svc = PortfolioFXService()
    return (
        svc.rate(db, quote_currency=quote, base_currency=base, as_of=as_of),
        svc.rate_with_provenance(db, quote_currency=quote, base_currency=base, as_of=as_of),
    )


def test_same_currency(db):
    r, p = _both(db, "eur", "EUR", date(2026, 1, 1))
    assert r == Decimal("1") and p["rate"] == r and p["direction"] == "same"


def test_no_rate(db):
    assert _both(db, "USD", "EUR", date(2026, 1, 1)) == (None, None)


def test_direct_and_latest_not_future(db):
    _add(db, "EUR", "USD", "0.9", date(2026, 1, 1), "a")
    _add(db, "EUR", "USD", "0.8", date(2026, 2, 1), "b")
    _add(db, "EUR", "USD", "0.1", date(2026, 3, 1), "future")
    r, p = _both(db, "USD", "EUR", date(2026, 2, 15))
    assert r == Decimal("0.8") == p["rate"]
    assert (p["rate_date"], p["source"], p["direction"]) == (date(2026, 2, 1), "b", "direct")


def test_inverse_is_reciprocal_with_source(db):
    _add(db, "USD", "EUR", "4", date(2026, 1, 1), "inv")
    r, p = _both(db, "USD", "EUR", date(2026, 1, 5))
    assert r == Decimal("0.25") == p["rate"]
    assert (p["source"], p["direction"]) == ("inv", "inverse")


def test_direct_preferred_over_inverse(db):
    _add(db, "EUR", "USD", "0.9", date(2026, 1, 1), "direct")
    _add(db, "USD", "EUR", "2", date(2026, 1, 3), "inv")
    r, p = _both(db, "USD", "EUR", date(2026, 1, 5))
    assert r == Decimal("0.9") and p["source"] == "direct"


# Desempate por created_at: inalcanzable, uq_fx_rate_tenant_pair_date impide dos
# filas con el mismo (tenant, base, quote, rate_date); ambos metodos conservan
# el mismo ORDER BY porque comparten implementacion.
