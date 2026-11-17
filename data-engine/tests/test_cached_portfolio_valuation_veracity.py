"""El total de cartera cacheado no mezcla divisas ni etiqueta fechas ajenas.

Antes ``get_portfolio_snapshot`` y ``get_positions_summary`` sumaban
``quantity * market_price`` en divisa NATIVA de cada posicion y publicaban la
suma bajo la etiqueta ``base_currency``: una cartera con EUR y USD devolvia
euros + dolares como un solo numero en euros. Y ``get_portfolio_snapshot``
aceptaba ``as_of`` y lo devolvia como ``snapshot_date`` valorando con las
posiciones actuales: una fecha que el dato no tenia. Estos tests fallan sin
el arreglo (reversion).
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Company, Portfolio, Position
from app.models.entities import Base
from app.services import cached_portfolio_valuation as portfolio
from app.services.portfolio_fx_service import PortfolioFXService


@pytest.fixture
def db_session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            db.info["tenant_id"] = "cache-veracity"
            yield db
    finally:
        engine.dispose()


def _seed(db: Session, *, usd_market_value_base: str | None = None):
    fund = Portfolio(name="Main", base_currency="EUR", tenant_id="cache-veracity")
    eur_co = Company(
        ticker="EUCO", name="Euro Co", exchange="X", currency="EUR",
        company_type="holding", valuation_model="unassigned",
    )
    usd_co = Company(
        ticker="USCO", name="Dollar Co", exchange="Y", currency="USD",
        company_type="holding", valuation_model="unassigned",
    )
    db.add_all([fund, eur_co, usd_co])
    db.flush()
    db.add_all([
        Position(
            company_id=eur_co.id, portfolio_id=fund.id, quantity=Decimal("2.5"),
            market_price=Decimal("12"), currency="EUR", tenant_id="cache-veracity",
            as_of=date(2026, 11, 10),
        ),
        Position(
            company_id=usd_co.id, portfolio_id=fund.id, quantity=Decimal("1"),
            market_price=Decimal("10"), currency="USD", tenant_id="cache-veracity",
            as_of=date(2026, 11, 10),
            market_value_base=(
                Decimal(usd_market_value_base) if usd_market_value_base is not None else None
            ),
        ),
    ])
    db.commit()
    return fund, eur_co, usd_co


def test_snapshot_total_is_none_when_a_position_lacks_base_value(db_session, monkeypatch):
    # Sin el arreglo este test falla: el total salia 40.0 (30 EUR + 10 USD
    # sumados como si fuesen euros) sin senal de mezcla.
    fund, _eur, usd = _seed(db_session)
    monkeypatch.setattr(PortfolioFXService, "ensure_portfolio", lambda self, session: fund)
    service = portfolio.CachedPortfolioValuationService()
    snapshot = service.get_portfolio_snapshot.__wrapped__(service, db_session)
    assert snapshot["total_value"] is None
    assert snapshot["total_value_complete"] is False
    assert snapshot["positions_missing_base_value"] == ["USCO"]
    by_symbol = {p["symbol"]: p for p in snapshot["positions"]}
    assert by_symbol["EUCO"]["value_base"] == 30.0
    assert by_symbol["USCO"]["value"] == 10.0 and by_symbol["USCO"]["value_base"] is None


def test_snapshot_uses_ledger_base_value_for_foreign_currency(db_session, monkeypatch):
    # Con el market_value_base del ledger (tipo real aplicado) el total es
    # completo y usa ESE valor, no el nativo.
    fund, _eur, _usd = _seed(db_session, usd_market_value_base="9.25")
    monkeypatch.setattr(PortfolioFXService, "ensure_portfolio", lambda self, session: fund)
    service = portfolio.CachedPortfolioValuationService()
    snapshot = service.get_portfolio_snapshot.__wrapped__(service, db_session)
    assert snapshot["total_value"] == 39.25
    assert snapshot["total_value_complete"] is True
    assert snapshot["positions_missing_base_value"] == []
    by_symbol = {p["symbol"]: p for p in snapshot["positions"]}
    assert by_symbol["USCO"]["value_base"] == 9.25


def test_summary_total_is_none_when_a_position_lacks_base_value(db_session, monkeypatch):
    fund, _eur, _usd = _seed(db_session)
    monkeypatch.setattr(PortfolioFXService, "ensure_portfolio", lambda self, session: fund)
    service = portfolio.CachedPortfolioValuationService()
    summary = service.get_positions_summary.__wrapped__(service, db_session)
    assert summary["total_value"] is None
    assert summary["total_value_complete"] is False
    assert summary["currencies"] == ["EUR", "USD"]


def test_snapshot_has_no_borrowed_date_label(db_session, monkeypatch):
    # Sin el arreglo existia ``snapshot_date`` (la fecha pedida estampada
    # sobre datos actuales) y el parametro as_of; ahora solo generated_at.
    fund, _eur, _usd = _seed(db_session)
    monkeypatch.setattr(PortfolioFXService, "ensure_portfolio", lambda self, session: fund)
    service = portfolio.CachedPortfolioValuationService()
    snapshot = service.get_portfolio_snapshot.__wrapped__(service, db_session)
    assert "snapshot_date" not in snapshot
    assert snapshot["generated_at"] == date.today().isoformat()
    with pytest.raises(TypeError):
        service.get_portfolio_snapshot.__wrapped__(service, db_session, as_of=date(2026, 1, 1))
