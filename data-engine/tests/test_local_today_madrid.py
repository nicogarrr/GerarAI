"""La fecha de «hoy» del usuario es la de Madrid, no la del servidor en UTC.

Produccion corre con TZ=UTC. A las 00:30 de Madrid del 28-oct-2026 (23:30 UTC
del 27) ``date.today()`` devuelve el 27: una compra de HOY (28) se rechazaba
como «fecha futura» en el ledger, en la API y en las fechas del declarante.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.api.routes.portfolio as portfolio_routes
import app.services.portfolio_ledger_service as ledger_module
import app.services.tax_declarant_service as declarant_module
from app.core.database import Base
from app.models import Tenant

# 00:30 en Madrid (CET, UTC+1 desde el 25-oct) = 23:30 UTC del dia anterior.
UTC_INSTANT = datetime(2026, 10, 27, 23, 30, tzinfo=UTC)
MADRID_TODAY = date(2026, 10, 28)


class _ServerDate(date):
    """date.today() de un servidor con TZ=UTC en ese instante."""

    @classmethod
    def today(cls):  # type: ignore[override]
        return cls(2026, 10, 27)


@pytest.fixture
def utc_server(monkeypatch):
    for module in (ledger_module, portfolio_routes, declarant_module):
        monkeypatch.setattr(module, "date", _ServerDate, raising=False)
    monkeypatch.setattr("app.core.local_date._utc_now", lambda: UTC_INSTANT)


def _db() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = Session(engine)
    tenant = Tenant(external_id="local-today", name="local today")
    db.add(tenant)
    db.flush()
    db.info["tenant_id"] = tenant.id
    return db


def test_compra_de_hoy_en_madrid_no_es_futura_en_el_ledger(utc_server):
    db = _db()
    transaction = ledger_module.PortfolioLedgerService().create_transaction(
        db, ticker="ZZTODAY", action="buy", quantity=Decimal("1"), price=Decimal("10"),
        trade_date=MADRID_TODAY, currency="USD",
    )
    assert transaction.trade_date == MADRID_TODAY


def test_manana_en_madrid_sigue_siendo_futura(utc_server):
    db = _db()
    with pytest.raises(ValueError, match="future"):
        ledger_module.PortfolioLedgerService().create_transaction(
            db, ticker="ZZTOMORROW", action="buy", quantity=Decimal("1"), price=Decimal("10"),
            trade_date=date(2026, 10, 29), currency="USD",
        )


def test_api_acepta_la_fecha_de_hoy_en_madrid(utc_server):
    payload = portfolio_routes.PortfolioTransactionInput(
        ticker="ZZTODAY", action="buy", quantity=Decimal("1"), price=Decimal("10"),
        trade_date=MADRID_TODAY,
    )
    assert payload.trade_date == MADRID_TODAY
    with pytest.raises(ValidationError):
        portfolio_routes.PortfolioTransactionInput(
            ticker="ZZTODAY", action="buy", quantity=Decimal("1"), price=Decimal("10"),
            trade_date=date(2026, 10, 29),
        )


def test_local_today_cambia_a_medianoche_de_madrid_no_de_utc():
    from app.core.local_date import local_today

    assert local_today(datetime(2026, 10, 27, 22, 59, tzinfo=UTC)) == date(2026, 10, 27)
    assert local_today(datetime(2026, 10, 27, 23, 0, tzinfo=UTC)) == date(2026, 10, 28)
    # Verano (CEST, UTC+2): el cambio de dia es a las 22:00 UTC.
    assert local_today(datetime(2026, 7, 1, 22, 0, tzinfo=UTC)) == date(2026, 7, 2)
