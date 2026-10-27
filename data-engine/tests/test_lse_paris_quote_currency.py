"""Londres/Euronext sin sufijo: simbolo Yahoo por bolsa y divisa de la COTIZACION.

Empresas guardadas con bolsa «LONDON STOCK EXCHANGE» / «EURONEXT PARIS» (y
Bruselas, Lisboa, Milan) y ticker sin sufijo no tenian simbolo Yahoo y se
quedaban sin precio. Ahora se pide la linea de esa bolsa (.L, .PA, ...). La
divisa del precio es SIEMPRE la que Yahoo declara para la cotizacion (SHEL.L:
GBp; SMSN.L: USD; MC.PA: EUR, verificado con yfinance 2026-10-27), nunca la
de las cuentas: SHEL reporta en USD y cotiza en peniques.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models import Company, FinancialFact, FXRate, MarketPrice, Tenant
from app.services.derived_market_cap_service import refresh_derived_market_cap
from app.services.market_change import compute_session_changes, ticker_close_change
from app.services.propicks_price_service import PriceBar, upsert_prices, yahoo_symbol
from app.services.screener_fundamentals import load_screener_ratios
from app.services.valuation_service import resolve_model_price

TODAY = date.today()


def _c(ticker, exchange, currency):
    return SimpleNamespace(ticker=ticker, exchange=exchange, currency=currency)


@pytest.mark.parametrize(
    ("ticker", "exchange", "currency", "expected"),
    [
        ("SHEL", "LONDON STOCK EXCHANGE", "USD", "SHEL.L"),
        ("CGEO", "LONDON STOCK EXCHANGE", "GBP", "CGEO.L"),
        ("MC", "EURONEXT PARIS", "EUR", "MC.PA"),
        ("MC", "NYSE EURONEXT - EURONEXT PARIS", "EUR", "MC.PA"),
        ("ABI", "EURONEXT BRUSSELS", "EUR", "ABI.BR"),
        ("ABI", "NYSE EURONEXT - EURONEXT BRUSSELS", "EUR", "ABI.BR"),
        ("GALP", "EURONEXT LISBON", "EUR", "GALP.LS"),
        ("GALP", "NYSE EURONEXT - EURONEXT LISBON", "EUR", "GALP.LS"),
        ("ENI", "BORSA ITALIANA", "EUR", "ENI.MI"),
        ("ENI", "EURONEXT MILAN", "EUR", "ENI.MI"),
        ("SAP", "DEUTSCHE BOERSE AG", "EUR", "SAP.DE"),
    ],
)
def test_bolsa_europea_da_su_sufijo_yahoo(ticker, exchange, currency, expected):
    assert yahoo_symbol(_c(ticker, exchange, currency)) == expected


def test_nunca_el_gemelo_us_ni_un_homonimo():
    # F166: SHEL pelado en Yahoo es el ADR de NYSE (USD ~104,78 el
    # 2026-10-27); con bolsa Londres se pide SHEL.L, jamas «SHEL».
    assert yahoo_symbol(_c("SHEL", "LONDON STOCK EXCHANGE", "USD")) != "SHEL"
    # Bolsas sin sufijo mapeado siguen sin simbolo (F164/F165) y la EUR sin
    # bolsa tampoco adivina .MC.
    assert yahoo_symbol(_c("TSM", "TAIWAN STOCK EXCHANGE", "TWD")) is None
    assert yahoo_symbol(_c("NVO", "OMX NORDIC EXCHANGE COPENHAGEN", "DKK")) is None
    assert yahoo_symbol(_c("SAN", "UNKNOWN", "EUR")) is None


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


def _company(db, ticker="SHEL", exchange="LONDON STOCK EXCHANGE", currency="USD"):
    company = Company(
        ticker=ticker, name=ticker, exchange=exchange, currency=currency,
        sector="Energy", industry="Oil", company_type="standard",
        valuation_model="standard_dcf", special_sources=[], special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.flush()
    return company


def _close(db, company, day, close, quote_currency, source="yfinance"):
    value = Decimal(close)
    db.add(MarketPrice(
        company_id=company.id, date=day, open=value, high=value, low=value,
        close=value, adj_close=value, volume=1000, source=source,
        quote_currency=quote_currency,
    ))


def _fx_gbp_usd(db, day, rate="1.30"):
    # quote amount x rate = base amount: 1 GBP = 1,30 USD.
    db.add(FXRate(base_currency="USD", quote_currency="GBP", rate=Decimal(rate),
                  rate_date=day, source="test", tenant_id=1))


def _bar(day, close, quote_currency):
    return PriceBar(day=day, close=Decimal(close), adj_close=Decimal(close), volume=10,
                    quote_currency=quote_currency, market_timezone="Europe/London")


NOW = datetime(2026, 10, 27, 20, 0, tzinfo=UTC)
OLD_DAY = date(2026, 10, 20)


def test_upsert_guarda_la_divisa_que_declara_yahoo(db):
    shel = _company(db)
    assert upsert_prices(db, shel, [_bar(OLD_DAY, "3927.5", "GBp")], now=NOW) == 1
    db.flush()
    row = db.scalar(select(MarketPrice).where(MarketPrice.company_id == shel.id))
    assert row.quote_currency == "GBp" and row.close == Decimal("3927.5")


def test_upsert_sin_divisa_de_la_cotizacion_no_supone_la_de_las_cuentas(db):
    # SHEL (LSE, cuentas USD) -> SHEL.L cotiza en peniques: una barra sin
    # divisa se leeria como 3.927 USD. Sin divisa declarada no se guarda.
    shel = _company(db)
    assert upsert_prices(db, shel, [_bar(OLD_DAY, "3927.5", None)], now=NOW) == 0
    # Paris en EUR con cuentas EUR: la unidad por defecto de la plaza
    # coincide con la del master y la barra sigue entrando como antes.
    mc = _company(db, ticker="MC", exchange="EURONEXT PARIS", currency="EUR")
    assert upsert_prices(db, mc, [_bar(OLD_DAY, "388.25", None)], now=NOW) == 1


def test_valoracion_usa_la_divisa_de_la_cotizacion_y_no_la_de_las_cuentas(db):
    shel = _company(db)
    _close(db, shel, OLD_DAY, "3927.5", "GBp")
    db.flush()
    price = resolve_model_price(db, shel.id)
    # 3.927,5 peniques = 39,275 GBP; la conversion GBP->USD la hace
    # _reconcile_currency con el tipo BCE del dia.
    assert price is not None
    assert price.currency == "GBP"
    assert price.value == pytest.approx(39.275)


def test_linea_de_londres_en_usd_queda_en_usd(db):
    # Algunas lineas .L cotizan en USD (SMSN.L, CSPX.L): manda la cotizacion.
    smsn = _company(db, ticker="SMSN", currency="KRW")
    _close(db, smsn, OLD_DAY, "4110", "USD")
    db.flush()
    price = resolve_model_price(db, smsn.id)
    assert price is not None and price.currency == "USD" and price.value == pytest.approx(4110)


def test_fila_fmp_antigua_del_gemelo_us_sigue_sin_usarse(db):
    # F159: filas FMP/Finnhub de emisores no-US llevan el USD del gemelo
    # americano. No se reinterpretan como precio valido.
    alm = _company(db, ticker="ALM", exchange="BME", currency="EUR")
    _close(db, alm, OLD_DAY, "13.72", "USD", source="FMP")
    db.flush()
    assert resolve_model_price(db, alm.id) is None


def _sessions(db, company, closes, quote_currency):
    days = [date(2026, 10, 19), date(2026, 10, 20)]
    for day, close in zip(days, closes, strict=True):
        _close(db, company, day, close, quote_currency)
    db.flush()


def test_variacion_del_cierre_en_la_divisa_de_la_cotizacion(db):
    shel = _company(db)
    _sessions(db, shel, ["3900", "3927.5"], "GBp")
    change = ticker_close_change(db, shel.id)
    assert change is not None
    assert change["currency"] == "GBP"
    assert change["close"] == pytest.approx(39.275)
    assert change["previous_close"] == pytest.approx(39.0)
    assert change["change_percent"] == pytest.approx((39.275 - 39.0) / 39.0 * 100)


def test_movers_muestran_el_precio_en_gbp(db):
    shel = _company(db)
    _sessions(db, shel, ["3900", "3927.5"], "GBp")
    movers, _stale, _day = compute_session_changes(db)
    row = next(m for m in movers if m["ticker"] == "SHEL")
    assert row["currency"] == "GBP"
    assert row["price"] == pytest.approx(39.275)
    assert row["change_pct"] == pytest.approx(0.71, abs=0.01)


def _shares(db, company, value):
    db.add(FinancialFact(
        company_id=company.id, metric="shares_outstanding", value=Decimal(value),
        unit="shares", period=TODAY.isoformat(), fiscal_year=None,
        fiscal_quarter=None, source_type="SEC", is_reported=True, tenant_id=1,
    ))


def test_market_cap_derivado_convierte_peniques_a_usd_con_fx(db):
    shel = _company(db)
    day = TODAY - timedelta(days=1)
    _close(db, shel, day, "3927.5", "GBp")
    _fx_gbp_usd(db, day)
    _shares(db, shel, "6000000000")
    db.flush()
    result = refresh_derived_market_cap(db, shel, today=TODAY)
    assert result["status"] == "ok"
    assert result["currency"] == "USD"
    assert result["market_cap"] == pytest.approx(39.275 * 1.30 * 6_000_000_000, rel=1e-9)


def test_market_cap_derivado_sin_fx_es_nd(db):
    shel = _company(db)
    day = TODAY - timedelta(days=1)
    _close(db, shel, day, "3927.5", "GBp")
    _shares(db, shel, "6000000000")
    db.flush()
    result = refresh_derived_market_cap(db, shel, today=TODAY)
    assert result == {"status": "unavailable", "reason": "no_fx_for_quote_currency"}


def test_per_del_screener_convierte_el_cierre_a_la_divisa_del_eps(db):
    shel = _company(db)
    day = TODAY - timedelta(days=1)
    _close(db, shel, day, "3927.5", "GBp")
    _fx_gbp_usd(db, day)
    db.add(FinancialFact(
        company_id=shel.id, metric="eps_diluted", value=Decimal("2.50"), unit="USD/share",
        period=f"{TODAY.year - 1}-12-31:FY", fiscal_year=TODAY.year - 1, fiscal_quarter="FY",
        source_type="SEC", is_reported=True, tenant_id=1,
    ))
    db.flush()
    out = load_screener_ratios(db, {"SHEL"}, today=TODAY)
    # 39,275 GBP x 1,30 = 51,0575 USD / 2,50 USD = 20,4x (no 1.571x).
    assert out["SHEL"]["pe"] == pytest.approx(39.275 * 1.30 / 2.50, rel=1e-6)


def test_per_de_la_watchlist_convierte_el_cierre_a_la_divisa_del_eps(db):
    from app.api.routes.watchlist import watchlist_metrics

    shel = _company(db)
    day = TODAY - timedelta(days=1)
    _close(db, shel, day, "3927.5", "GBp")
    _fx_gbp_usd(db, day)
    db.add(FinancialFact(
        company_id=shel.id, metric="eps_diluted", value=Decimal("2.50"), unit="USD/share",
        period=f"{TODAY.year - 1}-12-31:FY", fiscal_year=TODAY.year - 1, fiscal_quarter="FY",
        source_type="SEC", is_reported=True, tenant_id=1,
    ))
    db.commit()
    out = watchlist_metrics("SHEL", db=db)
    assert out["per"] == pytest.approx(39.275 * 1.30 / 2.50, rel=1e-6)
