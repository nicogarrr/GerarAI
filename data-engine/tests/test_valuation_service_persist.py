"""ValuationService persistence + price-resolution contracts.

persist_output is the write path of the valuation pipeline: statuses must
reflect publishability honestly (insufficient_data audits must survive as
such), versions must increment, and scenario outputs must skip missing
values instead of fabricating them. _position_price must prefer the stored
position price over stale market closes and never invent a price.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, MarketPrice, Position, ValuationOutput
from app.services.valuation_service import ValuationService, _position_price


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db: Session) -> Company:
    company = Company(
        ticker="ASTS", name="AST", exchange="NASDAQ", currency="USD",
        sector="Space", industry="Space", company_type="holding",
        valuation_model="pre_revenue", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _valuation(**over):
    base = {
        "status": "ok",
        "publishable": True,
        "model_type": "pre_revenue",
        "trace": {"engine": "pre_revenue"},
        "bear_value": 10.0,
        "base_value": 20.0,
        "bull_value": 30.0,
    }
    base.update(over)
    return base


def test_publishable_persists_final_with_scenarios(db):
    company = _company(db)
    model = ValuationService().persist_output(db, company, _valuation())
    assert model.status == "final"
    assert model.version == 1
    assert model.calculation_trace["engine"] == "pre_revenue"
    outputs = list(db.scalars(
        select(ValuationOutput).where(ValuationOutput.valuation_model_id == model.id)
    ))
    by_scenario = {o.scenario: float(o.value_per_share) for o in outputs}
    assert by_scenario == {"bear": 10.0, "base": 20.0, "bull": 30.0}


def test_missing_scenarios_are_skipped_never_filled(db):
    company = _company(db)
    model = ValuationService().persist_output(
        db, company, _valuation(bear_value=None, bull_value=None)
    )
    outputs = list(db.scalars(
        select(ValuationOutput).where(ValuationOutput.valuation_model_id == model.id)
    ))
    assert [o.scenario for o in outputs] == ["base"]


def test_insufficient_data_persists_as_audit_draft(db):
    company = _company(db)
    model = ValuationService().persist_output(
        db, company,
        _valuation(status="insufficient_data", publishable=False,
                   bear_value=None, base_value=None, bull_value=None),
    )
    assert model.status == "insufficient_data"
    outputs = list(db.scalars(
        select(ValuationOutput).where(ValuationOutput.valuation_model_id == model.id)
    ))
    assert outputs == []


def test_unpublishable_but_sufficient_is_draft(db):
    company = _company(db)
    model = ValuationService().persist_output(
        db, company, _valuation(status="ok", publishable=False)
    )
    assert model.status == "draft"


def test_versions_increment_per_company(db):
    company = _company(db)
    service = ValuationService()
    first = service.persist_output(db, company, _valuation())
    second = service.persist_output(db, company, _valuation())
    assert (first.version, second.version) == (1, 2)


def test_position_price_wins_over_stale_market_close(db):
    company = _company(db)
    db.add_all([
        Position(company_id=company.id, quantity=Decimal("1"), market_price=Decimal("150")),
        MarketPrice(
            company_id=company.id, date=date(2026, 9, 22),
            open=Decimal("100"), high=Decimal("101"), low=Decimal("99"),
            close=Decimal("100"), adj_close=Decimal("100"), source="Finnhub",
        ),
    ])
    db.commit()
    assert _position_price(db, company.id) == 150.0


def test_falls_back_to_latest_close_then_none(db):
    company = _company(db)
    db.add_all([
        MarketPrice(
            company_id=company.id, date=date(2026, 9, 20),
            open=Decimal("90"), high=Decimal("95"), low=Decimal("89"),
            close=Decimal("94"), adj_close=Decimal("94"), source="Finnhub",
        ),
        MarketPrice(
            company_id=company.id, date=date(2026, 9, 22),
            open=Decimal("100"), high=Decimal("101"), low=Decimal("99"),
            close=Decimal("100"), adj_close=Decimal("100"), source="Finnhub",
        ),
    ])
    db.commit()
    assert _position_price(db, company.id) == 100.0
    other = Company(
        ticker="NOPX", name="No Price", exchange="NYSE", currency="USD",
        sector="S", industry="I", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(other)
    db.commit()
    assert _position_price(db, other.id) is None


def test_price_as_of_from_latest_close(db):
    """F348: el precio del modelo declara su fecha (ultimo cierre en DB)."""
    from app.services.valuation_service import _position_price_as_of
    company = _company(db)
    db.add_all([
        MarketPrice(
            company_id=company.id, date=date(2026, 9, 20),
            open=Decimal("90"), high=Decimal("95"), low=Decimal("89"),
            close=Decimal("94"), adj_close=Decimal("94"), source="Finnhub",
        ),
        MarketPrice(
            company_id=company.id, date=date(2026, 9, 22),
            open=Decimal("100"), high=Decimal("101"), low=Decimal("99"),
            close=Decimal("100"), adj_close=Decimal("100"), source="Finnhub",
        ),
    ])
    db.commit()
    assert _position_price_as_of(db, company.id) == "2026-09-22"


def test_price_as_of_nunca_es_el_updated_at_de_la_posicion(db):
    """F348: el mark de la posicion no tiene fecha propia; updated_at es la
    ultima modificacion de la fila (una reconstruccion por transaccion nueva
    conserva el precio viejo pero mueve updated_at). Jamas se rotula el
    precio con esa fecha: None honesto aunque la fila se acabe de tocar."""
    from app.services.valuation_service import _position_price_as_of
    company = _company(db)
    pos = Position(company_id=company.id, quantity=Decimal("1"), market_price=Decimal("100"))
    db.add(pos)
    db.commit()
    # Simula la reconstruccion del auditor: nueva transaccion dias despues,
    # precio conservado, fila modificada -> updated_at se mueve.
    pos.quantity = Decimal("5")
    db.commit()
    db.refresh(pos)
    assert float(pos.market_price) == 100.0
    assert _position_price_as_of(db, company.id) is None


def test_price_as_of_none_without_price(db):
    """F348: sin precio no hay fecha (None honesto, nunca fabricada)."""
    from app.services.valuation_service import _position_price_as_of
    company = _company(db)
    assert _position_price_as_of(db, company.id) is None


def test_position_price_respects_as_of_cutoff(db):
    company = _company(db)
    db.add(MarketPrice(company_id=company.id, date=date(2025, 1, 10), close=Decimal("10")))
    db.add(MarketPrice(company_id=company.id, date=date(2025, 6, 10), close=Decimal("20")))
    db.add(Position(company_id=company.id, quantity=Decimal("1"), market_price=Decimal("99")))
    db.commit()

    # Sin cutoff se mantiene la precedencia vigente (posicion primero).
    assert _position_price(db, company.id) == 99.0
    # Con cutoff: ni el mark de la posicion (precio de hoy) ni cierres posteriores.
    assert _position_price(db, company.id, date(2025, 3, 1)) == 10.0
    assert _position_price(db, company.id, date(2025, 6, 10)) == 20.0
    assert _position_price(db, company.id, date(2024, 12, 31)) is None


def test_traceable_wacc_ignores_metric_created_after_cutoff(db):
    from datetime import datetime, timezone

    from app.models.entities import CalculatedMetric
    from app.valuation.engines.base import traceable_wacc

    company = _company(db)
    db.add(
        CalculatedMetric(
            company_id=company.id, metric="wacc", value=Decimal("0.09"), period="2025",
            fiscal_year=2025, status="ok", formula="f",
            created_at=datetime(2025, 6, 1, tzinfo=timezone.utc),
        )
    )
    db.commit()

    assert traceable_wacc(db, company) == pytest.approx(0.09)
    assert traceable_wacc(db, company, as_of=date(2025, 6, 1)) == pytest.approx(0.09)
    assert traceable_wacc(db, company, as_of=date(2025, 5, 31)) is None
