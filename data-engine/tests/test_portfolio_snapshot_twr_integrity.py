"""TWR integrity: F362 (previous coverage/base), F378 (currency), F379 (gaps)."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, Position, Transaction
from app.services.portfolio_fx_service import PortfolioFXService
from app.services.portfolio_snapshot_service import PortfolioSnapshotService

D0 = date(2026, 9, 1)
D1 = D0 + timedelta(days=1)
D2 = D0 + timedelta(days=2)


@pytest.fixture
def setup():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.info["tenant_id"] = "tenant-test"
        company = Company(
            ticker="AAPL", name="Apple", exchange="NASDAQ", currency="USD",
            sector="Tech", industry="Tech", company_type="holding",
            valuation_model="unassigned", special_sources=[], special_risks=[],
            factor_tags=[],
        )
        db.add(company)
        db.commit()
        portfolio = PortfolioFXService().ensure_portfolio(db)
        position = Position(
            portfolio_id=portfolio.id, company_id=company.id, quantity=Decimal("10"),
            market_price=Decimal("100"), currency="EUR", as_of=D0,
        )
        db.add(position)
        db.commit()
        yield db, portfolio, position


def _snap(db, day, position, price):
    position.as_of = day
    position.market_price = Decimal(price)
    db.commit()
    return PortfolioSnapshotService().capture(db, as_of=day)


def test_partial_previous_coverage_gives_no_return(setup):
    db, portfolio, position = setup
    first = _snap(db, D0, position, "100")
    first.pricing_coverage = Decimal("0.5")
    db.commit()
    second = _snap(db, D1, position, "200")
    assert second.daily_return is None
    assert second.cumulative_twr is None


def test_broken_series_does_not_restart_from_zero(setup):
    db, portfolio, position = setup
    _snap(db, D0, position, "100")
    second = _snap(db, D1, position, "110")
    second.cumulative_twr = None
    second.daily_return = None
    db.commit()
    third = _snap(db, D2, position, "120")
    assert third.cumulative_twr is None


def test_clean_link_after_gap_flow_block_does_not_restart_series(setup):
    """Caracterizacion: tras un bloqueo por flujo en dia sin foto, un enlace
    posterior limpio NO reinicia la cadena (fail-closed por diseno).

    La foto bloqueada esta completa y valorable, y el tramo nuevo seria
    calculable, pero ``_restart_base`` solo admite base nueva tras un tramo
    NO valorable (cobertura < 1 o valor <= 0), no tras un bloqueo por flujos
    sin valorar. La reparacion es la herramienta twr_rebuild, nunca un
    reinicio silencioso. Comportamiento actual (fail-closed documentado en
    el servicio).
    """
    db, portfolio, position = setup
    _snap(db, D0, position, "100")  # base, total 1000
    # Deposito en D1 (dia SIN foto) y foto en D2: el enlace D0->D2 se bloquea.
    db.add(
        Transaction(
            portfolio_id=portfolio.id, trade_date=D1, action="deposit",
            quantity=Decimal("1"), price=Decimal("500"), currency="EUR",
            external_id="dep-gap-nr",
        )
    )
    position.quantity = Decimal("15")
    db.commit()
    blocked = _snap(db, D2, position, "110")  # completa, pero sin retorno
    assert blocked.pricing_coverage == Decimal("1")
    assert blocked.daily_return is None and blocked.cumulative_twr is None
    assert blocked.metadata_["unvalued_intermediate_flows"] == 1
    # Enlace D2->D3 completamente limpio (ambas completas, sin flujos): la
    # serie sigue sin reiniciarse.
    d3 = D2 + timedelta(days=1)
    clean = _snap(db, d3, position, "112")
    assert clean.pricing_coverage == Decimal("1")
    assert clean.daily_return is None
    assert clean.cumulative_twr is None


def test_previous_different_currency_gives_no_return(setup):
    db, portfolio, position = setup
    first = _snap(db, D0, position, "100")
    first.base_currency = "USD"
    db.commit()
    second = _snap(db, D1, position, "110")
    assert second.daily_return is None


def test_gap_without_intermediate_flow_gives_interval_return(setup):
    db, portfolio, position = setup
    _snap(db, D0, position, "100")  # total 1000
    third = _snap(db, D2, position, "110")  # total 1100, no snapshot on D1
    assert third.daily_return == pytest.approx(Decimal("0.1"))
    assert third.metadata_["interval_days"] == 2


def test_gap_with_unvalued_intermediate_flow_gives_no_return(setup):
    """Auditor case: +10%, deposit 500 without snapshot, +10%; true TWR is 21%."""
    db, portfolio, position = setup
    _snap(db, D0, position, "100")  # total 1000
    db.add(
        Transaction(
            portfolio_id=portfolio.id, trade_date=D1, action="deposit",
            quantity=Decimal("1"), price=Decimal("500"), currency="EUR",
            external_id="dep-gap",
        )
    )
    db.commit()
    position.quantity = Decimal("15")
    third = _snap(db, D2, position, "117.333333")  # ~1760
    assert third.daily_return is None
    assert third.cumulative_twr is None
    assert third.metadata_["twr_blocked_by_gap_flows"] is True
    assert third.metadata_["unvalued_intermediate_flows"] == 1
