"""realqa-10: compras en USD de una cuenta EUR salian sin coste ni G/P.

Reproducido en produccion (27-oct-2026): cuenta EUR nueva, 7 compras en USD del
02/03/2026. Valor de mercado correcto, pero coste, G/P, rentabilidad y pesos en
N/D («Conversion o coste no disponible») en las 7. Causa: `fx_rates` solo
tenia los tipos del refresco diario (posteriores a esa fecha) y la descarga
historica del BCE (#2349) no la llamaba nadie, asi que `rebuild_position` no
encontraba tipo para la fecha de compra y dejaba `cost_basis_base = None`.

Calculo a mano (BCE publica USD por 1 EUR; la tabla guarda EUR por 1 USD):
  27/02/2026 (viernes): 1,0400 USD/EUR -> 1 USD = 0,961538... EUR
  02/03/2026 (lunes):   1,0500 USD/EUR -> 1 USD = 0,952380... EUR
  Compra de 10 AAPL a 200 $ el 02/03/2026 -> coste 2.000 $ = 1.904,76 EUR.
  Compra del domingo 01/03/2026 -> usa el viernes 27/02: 2.000 $ = 1.923,08 EUR.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.entities import Base, FXRate, Portfolio
from app.services import portfolio_ledger_service as ledger_mod
from app.services.connectors.ecb_history import backfill_ecb_rates_sync
from app.services.portfolio_ledger_service import PortfolioLedgerService

CSV = (
    "KEY,FREQ,CURRENCY,CURRENCY_DENOM,EXR_TYPE,EXR_SUFFIX,TIME_PERIOD,OBS_VALUE,OBS_STATUS\n"
    "EXR.D.USD.EUR.SP00.A,D,USD,EUR,SP00,A,2026-02-27,1.0400,A\n"
    "EXR.D.USD.EUR.SP00.A,D,USD,EUR,SP00,A,2026-03-02,1.0500,A\n"
)


@pytest.fixture
def db():
    ledger_mod._ECB_BACKFILL_TRIED.clear()
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        session.add(Portfolio(name="Main", base_currency="EUR", is_default=True))
        # Lo que habia en prod: solo el tipo del refresco diario de hoy.
        session.add(FXRate(base_currency="EUR", quote_currency="USD", rate=Decimal("0.86"),
                           rate_date=date(2026, 10, 27), source="market_refresh"))
        session.commit()
        yield session


def _ecb_backfill(calls):
    def fetch(codes, start, end):
        calls.append((tuple(codes), start, end))
        return CSV

    def backfill(db, currencies, start, end):
        return backfill_ecb_rates_sync(db, currencies=currencies, start=start, end=end, fetcher=fetch)

    return backfill


def _buy(service, db, day):
    service.create_transaction(
        db, ticker="AAPL", action="buy", quantity=Decimal("10"), price=Decimal("200"),
        trade_date=day, fees=Decimal("0"), currency="USD", notes=None,
    )
    db.commit()
    from app.models import Position

    return db.scalar(select(Position))


def test_sin_backfill_el_coste_queda_no_disponible(db):
    """Lo que veia el usuario: sin tipo en la fecha de compra no hay coste base."""
    position = _buy(PortfolioLedgerService(), db, date(2026, 3, 2))
    assert position.cost_basis_base is None
    assert position.unrealized_pnl_base is None


def test_falta_el_tipo_de_la_fecha_se_descarga_el_bce_y_hay_coste(db):
    calls = []
    service = PortfolioLedgerService(fx_backfill=_ecb_backfill(calls))
    position = _buy(service, db, date(2026, 3, 2))

    assert calls and calls[0][0] == ("USD",)
    assert calls[0][1] <= date(2026, 2, 23)  # unos dias antes: fines de semana/festivos
    assert position.cost_basis_base is not None
    assert position.cost_basis_base.quantize(Decimal("0.01")) == Decimal("1904.76")
    assert position.unrealized_pnl_base is not None
    found = service.fx.rate_with_provenance(db, quote_currency="USD", base_currency="EUR",
                                            as_of=date(2026, 3, 2))
    assert found is not None
    assert found["rate_date"] == date(2026, 3, 2) and found["source"] == "ECB"


def test_compra_en_domingo_usa_el_ultimo_tipo_publicado_anterior(db):
    service = PortfolioLedgerService(fx_backfill=_ecb_backfill([]))
    position = _buy(service, db, date(2026, 3, 1))
    assert position.cost_basis_base.quantize(Decimal("0.01")) == Decimal("1923.08")
    found = service.fx.rate_with_provenance(db, quote_currency="USD", base_currency="EUR",
                                            as_of=date(2026, 3, 1))
    assert found is not None
    assert found["rate_date"] == date(2026, 2, 27)


def test_si_ya_hay_tipo_no_se_descarga(db):
    db.add(FXRate(base_currency="EUR", quote_currency="USD", rate=Decimal("0.95"),
                  rate_date=date(2026, 3, 2), source="ECB"))
    db.commit()
    calls = []
    _buy(PortfolioLedgerService(fx_backfill=_ecb_backfill(calls)), db, date(2026, 3, 2))
    assert calls == []


def test_si_el_bce_falla_no_rompe_la_compra_y_no_reintenta_en_bucle(db):
    calls = []

    def boom(db, currencies, start, end):
        calls.append(1)
        raise RuntimeError("bce caido")

    service = PortfolioLedgerService(fx_backfill=boom)
    position = _buy(service, db, date(2026, 3, 2))
    assert position.cost_basis_base is None  # degrada a «no disponible», sin 500
    service.rebuild_position(db, position.company_id)
    assert calls == [1]


def test_base_no_eur_no_llama_al_bce(db):
    db.scalar(select(Portfolio)).base_currency = "USD"
    db.commit()
    calls = []
    _buy(PortfolioLedgerService(fx_backfill=_ecb_backfill(calls)), db, date(2026, 3, 2))
    assert calls == []
