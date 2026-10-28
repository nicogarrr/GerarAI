"""Divisa base: EUR <-> USD, reparto de la G/P en efecto precio y efecto divisa,
y la fiscalidad siempre en EUR aunque la base sea USD.

Numeros a mano. Compra 10 x 100 USD el 2-ene (1 USD = 0,90 EUR) y cotiza a
120 USD el 2-feb (1 USD = 0,80 EUR):
- coste en EUR = 1.000 x 0,90 = 900; valor en EUR = 1.200 x 0,80 = 960;
- G/P en EUR = 60 = efecto precio (200 USD x 0,80 = 160) + efecto divisa
  (1.000 USD x 0,80 - 900 = -100).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Company, Position
from app.services.fx_attribution import split_unrealized_pnl
from app.services.portfolio_fx_service import TAX_CURRENCY, PortfolioFXService
from app.services.portfolio_ledger_service import PortfolioLedgerService
from app.services.tax_report_service import TaxReportService


def _company(db: Session) -> Company:
    company = Company(
        ticker="FXCO",
        name="FX Company",
        exchange="NYSE",
        currency="USD",
        sector="Test",
        industry="Test",
        company_type="generic",
        valuation_model="dcf",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.flush()
    return company


def _rates(db: Session) -> None:
    fx = PortfolioFXService()
    # Tabla BCE: base EUR. 1 USD x rate = EUR.
    for day, rate in ((date(2026, 1, 2), "0.90"), (date(2026, 2, 2), "0.80")):
        fx.upsert_rate(
            db, base_currency="EUR", quote_currency="USD", rate=Decimal(rate), rate_date=day, source="ECB"
        )
        # Misma informacion vista desde USD: 1 EUR x (1/rate) = USD.
        fx.upsert_rate(
            db,
            base_currency="USD",
            quote_currency="EUR",
            rate=Decimal(1) / Decimal(rate),
            rate_date=day,
            source="ECB",
        )


def _buy_and_mark(db: Session, company: Company) -> None:
    ledger = PortfolioLedgerService()
    ledger.create_transaction(
        db,
        ticker=company.ticker,
        action="buy",
        quantity=Decimal("10"),
        price=Decimal("100"),
        trade_date=date(2026, 1, 2),
        currency="USD",
    )
    ledger.update_market_price(db, company_id=company.id, price=Decimal("120"), as_of=date(2026, 2, 2))


def _rebuild_all(db: Session) -> None:
    ledger = PortfolioLedgerService()
    for company_id in db.scalars(select(Position.company_id)).all():
        ledger.rebuild_position(db, company_id)


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_reparto_efecto_precio_y_divisa_suma_la_gp_en_base(db: Session) -> None:
    company = _company(db)
    PortfolioFXService().set_base_currency(db, "EUR")
    _rates(db)
    _buy_and_mark(db, company)
    db.commit()

    position = db.scalar(select(Position).where(Position.company_id == company.id))
    assert position is not None
    assert position.unrealized_pnl_base == Decimal("60")
    price_effect, fx_effect = split_unrealized_pnl(
        unrealized_native=position.unrealized_pnl,
        unrealized_base=position.unrealized_pnl_base,
        fx_rate_now=position.fx_rate,
    )
    # 200 USD x 0,80 = 160 EUR de precio; 1.000 x 0,80 - 900 = -100 EUR de divisa.
    assert price_effect is not None and fx_effect is not None
    assert price_effect == pytest.approx(160.0)
    assert fx_effect == pytest.approx(-100.0)
    assert price_effect + fx_effect == pytest.approx(60.0)


def test_misma_divisa_no_tiene_efecto_divisa() -> None:
    price_effect, fx_effect = split_unrealized_pnl(
        unrealized_native=Decimal("200"), unrealized_base=Decimal("200"), fx_rate_now=1
    )
    assert price_effect == pytest.approx(200.0)
    assert fx_effect == pytest.approx(0.0)


def test_sin_tipo_no_se_inventa_el_reparto() -> None:
    assert split_unrealized_pnl(
        unrealized_native=Decimal("200"), unrealized_base=None, fx_rate_now=Decimal("0.8")
    ) == (None, None)
    assert split_unrealized_pnl(
        unrealized_native=Decimal("200"), unrealized_base=Decimal("60"), fx_rate_now=None
    ) == (None, None)


def test_cambiar_divisa_base_eur_a_usd_y_volver(db: Session) -> None:
    company = _company(db)
    fx = PortfolioFXService()
    fx.set_base_currency(db, "EUR")
    _rates(db)
    _buy_and_mark(db, company)
    db.commit()

    # A USD: la posicion es USD, asi que base = nativa y el efecto divisa es 0.
    fx.set_base_currency(db, "USD")
    _rebuild_all(db)
    db.commit()
    position = db.scalar(select(Position).where(Position.company_id == company.id))
    assert position is not None
    assert position.base_currency == "USD"
    assert position.market_value_base == Decimal("1200")
    assert position.cost_basis_base == Decimal("1000")
    assert position.unrealized_pnl_base == Decimal("200")

    # De vuelta a EUR: los mismos 960 / 900 / 60 que al principio. Nada
    # almacenado se reescribio: el ledger guarda importes nativos.
    fx.set_base_currency(db, "EUR")
    _rebuild_all(db)
    db.commit()
    position = db.scalar(select(Position).where(Position.company_id == company.id))
    assert position is not None
    assert position.market_value_base == Decimal("960")
    assert position.cost_basis_base == Decimal("900")
    assert position.unrealized_pnl_base == Decimal("60")


def test_fiscalidad_en_eur_aunque_la_base_sea_usd(db: Session) -> None:
    # Venta: 10 x 120 USD el 2-feb. Criterio DGT (consultas vinculantes V1740-17,
    # V0706-22 y V0152-26, 27/01/2026): «debiendo efectuarse dicho cálculo en la
    # moneda en que se encuentren denominadas las acciones y efectuar la conversión
    # de la diferencia resultante a euros al tipo de cambio vigente en la fecha en
    # la que haya tenido lugar la alteración patrimonial».
    # Ganancia en USD: 1.200 - 1.000 = 200 USD; x 0,80 (BCE del 2-feb) = 160 EUR.
    # (La diferencia de cambio de las divisas es otra ganancia, aparte, al convertirlas.)
    company = _company(db)
    fx = PortfolioFXService()
    fx.set_base_currency(db, "USD")
    _rates(db)
    ledger = PortfolioLedgerService()
    ledger.create_transaction(
        db,
        ticker=company.ticker,
        action="buy",
        quantity=Decimal("10"),
        price=Decimal("100"),
        trade_date=date(2026, 1, 2),
        currency="USD",
    )
    ledger.create_transaction(
        db,
        ticker=company.ticker,
        action="sell",
        quantity=Decimal("10"),
        price=Decimal("120"),
        trade_date=date(2026, 2, 2),
        currency="USD",
    )
    db.commit()

    report = TaxReportService().compute_report(db, 2026, include_filing=False)

    assert TAX_CURRENCY == "EUR"
    assert report["summary"]["base_currency"] == "EUR"
    # 200 USD de ganancia convertidos al tipo BCE de la fecha de venta: 160 EUR
    # (no 960 - 900 = 60 convirtiendo cada pata a su fecha).
    assert Decimal(str(report["summary"]["total_realized_gain_base"])) == Decimal("160")
