"""``resolve_fx`` must keep minor units (pence) distinct from the major unit.

Found by mutation testing: ``resolve_fx`` upper-cased its inputs, so
``resolve_fx(db, "GBp", "USD", on)`` silently returned the POUND rate and any
caller passing a pence-quoted price got a x100 conversion. The FX service
underneath (``rate_with_provenance``) already handles pence; the upper-casing
threw that information away before reaching it.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, FXRate
from app.valuation.currency import resolve_fx

ON = date(2026, 9, 30)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        # quote amount x rate = base amount: 1 GBP = 1.30 USD
        session.add(
            FXRate(
                base_currency="USD",
                quote_currency="GBP",
                rate=Decimal("1.30"),
                rate_date=date(2026, 9, 29),
                source="ecb",
            )
        )
        session.add(
            FXRate(
                base_currency="EUR",
                quote_currency="GBP",
                rate=Decimal("1.20"),
                rate_date=date(2026, 9, 29),
                source="ecb",
            )
        )
        session.add(
            FXRate(
                base_currency="EUR",
                quote_currency="CNY",
                rate=Decimal("0.125"),
                rate_date=date(2026, 9, 29),
                source="ecb",
            )
        )
        session.commit()
        yield session
    engine.dispose()


def test_pence_to_dollars_divides_by_100(db):
    q = resolve_fx(db, "GBp", "USD", ON)
    assert q is not None
    assert q.rate == pytest.approx(0.013)  # 1 penny = 0.013 USD, not 1.30
    assert q.from_currency == "GBp"


def test_gbx_alias_is_pence_too(db):
    assert resolve_fx(db, "GBX", "USD", ON).rate == pytest.approx(0.013)


def test_dollars_to_pence_multiplies_by_100(db):
    assert resolve_fx(db, "USD", "GBp", ON).rate == pytest.approx(100 / 1.30)


def test_pence_to_pounds_is_exactly_one_hundredth_without_any_fx_row(db):
    q = resolve_fx(db, "GBp", "GBP", ON)
    assert q is not None
    assert q.rate == pytest.approx(0.01)


def test_pence_cross_rate_through_pivot(db):
    q = resolve_fx(db, "GBp", "CNY", ON)
    assert q is not None
    assert q.rate == pytest.approx(0.012 / 0.125)
    assert q.path == ("GBp", "EUR", "CNY")


def test_major_unit_codes_are_still_case_insensitive(db):
    assert resolve_fx(db, "gbp", "usd", ON).rate == pytest.approx(1.30)
