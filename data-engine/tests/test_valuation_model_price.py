"""Precio del modelo: el mas fresco y en la unidad principal del listado.

Regresion (auditoria de divisas, 27-oct-2026):
- ``_position_price`` preferia ``Position.market_price`` de CUALQUIER fila
  (tambien una posicion cerrada, elegida con ``limit(1)`` sin orden) frente a un
  cierre de mercado mas reciente.
- Londres cotiza en peniques: un cierre de 4.255 GBX se comparaba con valores
  en libras (error x100 en CGEO.L).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models import Company, MarketPrice, Portfolio, Position, Tenant
from app.services.valuation_service import (
    _position_price,
    _position_price_as_of,
    resolve_model_price,
)


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Tenant(id=1, external_id="t1"))
        session.commit()
        session.info["tenant_id"] = 1
        yield session
    engine.dispose()


def _company(db: Session, ticker: str = "BABA", currency: str = "USD") -> Company:
    company = Company(
        ticker=ticker,
        name=ticker,
        exchange="NYSE",
        currency=currency,
        company_type="standard",
        valuation_model="standard_dcf",
    )
    db.add(company)
    db.add(Portfolio(name="Principal", base_currency="EUR", is_default=True))
    db.flush()
    return company


def _position(
    db: Session,
    company: Company,
    *,
    quantity: str,
    mark: str,
    as_of: date,
    currency: str = "USD",
    source: str = "ibkr_flex",
) -> None:
    portfolio = db.query(Portfolio).first()
    db.add(
        Position(
            portfolio_id=portfolio.id if portfolio else None,
            company_id=company.id,
            quantity=Decimal(quantity),
            market_price=Decimal(mark),
            currency=currency,
            as_of=as_of,
            source=source,
        )
    )


def _close(db: Session, company: Company, day: date, close: str) -> None:
    value = Decimal(close)
    db.add(
        MarketPrice(
            company_id=company.id,
            date=day,
            open=value,
            high=value,
            low=value,
            close=value,
            source="test",
        )
    )


def test_cierre_mas_reciente_gana_al_mark_antiguo(db: Session) -> None:
    company = _company(db)
    _position(db, company, quantity="10", mark="80", as_of=date(2026, 9, 30))
    _close(db, company, date(2026, 10, 23), "120")
    db.commit()

    assert _position_price(db, company.id) == 120.0
    assert _position_price_as_of(db, company.id) == "2026-10-23"


def test_mark_mas_reciente_gana_al_cierre_antiguo(db: Session) -> None:
    company = _company(db)
    _close(db, company, date(2026, 10, 1), "120")
    _position(db, company, quantity="10", mark="131.5", as_of=date(2026, 10, 24))
    db.commit()

    resolved = resolve_model_price(db, company.id)
    assert resolved is not None
    assert resolved.value == 131.5
    assert resolved.source == "position_mark"
    assert _position_price_as_of(db, company.id) == "2026-10-24"


def test_a_igual_fecha_gana_el_cierre_oficial(db: Session) -> None:
    company = _company(db)
    _close(db, company, date(2026, 10, 23), "120")
    _position(db, company, quantity="10", mark="119", as_of=date(2026, 10, 23))
    db.commit()

    assert _position_price(db, company.id) == 120.0


def test_mark_manual_sin_fecha_no_gana_a_un_cierre(db: Session) -> None:
    # Fila manual: su as_of es el default de la columna, no la fecha del precio.
    company = _company(db)
    _close(db, company, date(2026, 10, 1), "120")
    _position(
        db, company, quantity="10", mark="80", as_of=date(2026, 10, 26), source="manual"
    )
    db.commit()

    assert _position_price(db, company.id) == 120.0


def test_mark_manual_como_respaldo_sin_cierre(db: Session) -> None:
    company = _company(db)
    _position(
        db, company, quantity="10", mark="80", as_of=date(2026, 10, 26), source="manual"
    )
    db.commit()

    assert _position_price(db, company.id) == 80.0
    assert _position_price_as_of(db, company.id) is None


def test_posicion_cerrada_no_aporta_precio(db: Session) -> None:
    company = _company(db)
    _position(db, company, quantity="0", mark="55", as_of=date(2026, 10, 26))
    db.commit()

    assert _position_price(db, company.id) is None
    assert _position_price_as_of(db, company.id) is None


def test_con_cutoff_solo_cierres_hasta_la_fecha(db: Session) -> None:
    company = _company(db)
    _position(db, company, quantity="10", mark="80", as_of=date(2026, 10, 26))
    _close(db, company, date(2026, 1, 2), "90")
    _close(db, company, date(2026, 10, 23), "120")
    db.commit()

    assert _position_price(db, company.id, date(2026, 6, 30)) == 90.0
    assert _position_price_as_of(db, company.id, date(2026, 6, 30)) == "2026-01-02"


def test_golden_cgeo_l_peniques_a_libras(db: Session) -> None:
    # Ficha creada con la divisa por defecto (USD), como hace el enriquecimiento:
    # el sufijo .L manda. Cierre Yahoo 16-oct-2026: 4.255 GBp.
    # A mano: 4255 / 100 = 42,55 GBP.
    company = _company(db, ticker="CGEO.L", currency="USD")
    _close(db, company, date(2026, 10, 16), "4255")
    db.commit()

    resolved = resolve_model_price(db, company.id)
    assert resolved is not None
    assert resolved.value == pytest.approx(42.55)
    assert resolved.currency == "GBP"
    assert resolved.source == "market_close"


def test_cgeo_l_mark_en_libras_no_se_divide(db: Session) -> None:
    # IBKR informa la posicion en GBP: el mark ya esta en libras.
    company = _company(db, ticker="CGEO.L", currency="USD")
    _close(db, company, date(2026, 10, 16), "4255")
    _position(
        db, company, quantity="100", mark="43.10", as_of=date(2026, 10, 20), currency="GBP"
    )
    db.commit()

    resolved = resolve_model_price(db, company.id)
    assert resolved is not None
    assert resolved.value == pytest.approx(43.10)
    assert resolved.currency == "GBP"
