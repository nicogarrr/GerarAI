"""Bordes de earnings_dates_service: zona horaria por sufijo, sesion yahoo
(crumb), fetch yahoo con cliente falso, escaneo NASDAQ con async client
falso, guard de refresh ante una fuente caida y dividendos de cartera.

Dobles declarados: httpx.Client / httpx.AsyncClient falsos por monkeypatch
(no hay red); time.sleep sustituido (monkeypatch del nombre ``time`` en el
modulo) para no esperar YAHOO_PAUSE_S; los fetchers de refresh son lambdas.
SQLite real en memoria para followed_calendar / portfolio_dividend_dates.

NO se prueba: Yahoo/NASDAQ reales (red), la ruta del calendario, ni el
contenido de las fechas mas alla del calculo por zona horaria declarado.
"""

from __future__ import annotations

import asyncio
from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.services.earnings_dates_service as eds
from app.models.entities import (
    Base,
    Company,
    DividendRecord,
    EarningsDate,
    Portfolio,
    Position,
    Tenant,
    WatchItem,
)


def test_market_timezone_sufijos_y_clases():
    assert eds.market_timezone("AAPL") == "America/New_York"
    assert eds.market_timezone("SAN.MC") == "Europe/Madrid"
    assert eds.market_timezone("7203.T") == "Asia/Tokyo"
    assert eds.market_timezone("BRK.B") == "America/New_York"  # clase US, no bolsa
    assert eds.market_timezone("aapl") == "America/New_York"   # case-insensitive
    assert eds.market_timezone("RARO.XX") is None              # bolsa desconocida
    assert eds.market_timezone(".MC") is None                  # sin cabeza
    assert eds.market_timezone("") is None


class _Resp:
    def __init__(self, text="", payload=None):
        self.text = text
        self._payload = payload or {}

    def json(self):
        return self._payload


class _HttpxClientFalso:
    """Doble declarado de httpx.Client: cookie + crumb + quoteSummary."""

    def __init__(self, crumb="crumb-ok", payloads=None, fallos=None):
        self.crumb = crumb
        self.payloads = payloads or {}
        self.fallos = fallos or set()
        self.cerrado = False

    def get(self, url, params=None):
        if "fc.yahoo.com" in url:
            return _Resp()
        if "getcrumb" in url:
            return _Resp(text=self.crumb)
        symbol = url.rsplit("/", 1)[-1]
        if symbol in self.fallos:
            raise OSError("yahoo caido")
        return _Resp(payload=self.payloads.get(symbol, {"quoteSummary": {"result": []}}))

    def close(self):
        self.cerrado = True


def _parchea_httpx(monkeypatch, cliente):
    monkeypatch.setattr(
        eds, "httpx", SimpleNamespace(Client=lambda **kwargs: cliente)
    )


def test_yahoo_session_ok_y_crumb_invalido(monkeypatch):
    cliente = _HttpxClientFalso(crumb="crumb-ok")
    _parchea_httpx(monkeypatch, cliente)
    sesion, crumb = eds._yahoo_session()
    assert sesion is cliente and crumb == "crumb-ok"
    for malo in ("", "con espacio", "x" * 41):
        _parchea_httpx(monkeypatch, _HttpxClientFalso(crumb=malo))
        with pytest.raises(RuntimeError, match="yahoo_crumb_unavailable"):
            eds._yahoo_session()


def test_fetch_yahoo_dates_sin_crumb_devuelve_vacio(monkeypatch):
    _parchea_httpx(monkeypatch, _HttpxClientFalso(crumb=""))
    assert eds.fetch_yahoo_dates({"AAPL": "AAPL"}) == {}


def test_fetch_yahoo_dates_calcula_en_zona_y_tolera_fallos(monkeypatch):
    # 2026-11-05 00:00 UTC = 2026-11-04 en America/New_York
    cliente = _HttpxClientFalso(
        payloads={
            "AAPL": {
                "quoteSummary": {
                    "result": [
                        {
                            "calendarEvents": {
                                "earnings": {
                                    "earningsDate": [{"raw": 1793836800}],
                                    "isEarningsDateEstimate": False,
                                }
                            }
                        }
                    ]
                }
            }
        },
        fallos={"MSFT"},
    )
    _parchea_httpx(monkeypatch, cliente)
    monkeypatch.setattr(eds, "time", SimpleNamespace(sleep=lambda s: None))
    out = eds.fetch_yahoo_dates({"AAPL": "AAPL", "MSFT": "MSFT", "SAN": "SAN.MC"})
    assert out == {"AAPL": {"date": date(2026, 11, 4), "estimate": False}}
    assert cliente.cerrado is True


def test_fetch_yahoo_dates_zona_desconocida_sin_fecha(monkeypatch):
    cliente = _HttpxClientFalso(
        payloads={
            "RARO.XX": {
                "quoteSummary": {
                    "result": [
                        {"calendarEvents": {"earnings": {"earningsDate": [{"raw": 1793836800}]}}}
                    ]
                }
            }
        }
    )
    _parchea_httpx(monkeypatch, cliente)
    monkeypatch.setattr(eds, "time", SimpleNamespace(sleep=lambda s: None))
    assert eds.fetch_yahoo_dates({"RARO": "RARO.XX"}) == {}


class _AsyncClientFalso:
    """Doble declarado de httpx.AsyncClient para el escaneo NASDAQ."""

    def __init__(self, filas_por_dia=None, fallos=0):
        self.filas_por_dia = filas_por_dia or {}
        self.intentos = 0
        self.fallos = fallos

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url, params=None, timeout=None):
        self.intentos += 1
        if self.intentos <= self.fallos:
            raise OSError("nasdaq caido")
        dia = date.fromisoformat(params["date"])
        return _Resp(payload={"data": {"rows": self.filas_por_dia.get(dia, [])}})


def test_nasdaq_day_reintenta_una_vez_y_rinde(monkeypatch):
    cliente = _AsyncClientFalso(fallos=2)  # dos intentos, los dos fallan
    out = asyncio.run(
        eds._nasdaq_day(cliente, date(2026, 11, 10), asyncio.Semaphore(4))
    )
    assert out == [] and cliente.intentos == 2


def test_nasdaq_day_exito_en_el_segundo_intento(monkeypatch):
    dia = date(2026, 11, 10)
    cliente = _AsyncClientFalso(filas_por_dia={dia: [{"symbol": "AAPL"}]}, fallos=1)
    out = asyncio.run(eds._nasdaq_day(cliente, dia, asyncio.Semaphore(4)))
    assert out == [{"symbol": "AAPL"}] and cliente.intentos == 2


def test_nasdaq_scan_primera_fecha_futura_y_sesion(monkeypatch):
    hoy = date(2026, 11, 9)  # lunes
    dia1, dia2 = date(2026, 11, 10), date(2026, 11, 11)
    cliente = _AsyncClientFalso(
        filas_por_dia={
            dia1: [{"symbol": "AAPL", "time": "time-after-hours", "fiscalQuarterEnding": "Sep/2026"}],
            dia2: [
                {"symbol": "AAPL", "time": "time-pre-market", "fiscalQuarterEnding": ""},
                {"symbol": "MSFT", "time": "", "fiscalQuarterEnding": ""},
            ],
        }
    )
    monkeypatch.setattr(
        eds, "httpx", SimpleNamespace(AsyncClient=lambda **kwargs: cliente)
    )
    out = asyncio.run(eds._nasdaq_scan({"AAPL", "MSFT"}, hoy))
    assert out == {
        "AAPL": {"date": dia1, "session": "after_market", "fiscal": "Sep/2026"},
        # la primera fecha futura gana; fiscal vacio y sesion desconocida -> None
        "MSFT": {"date": dia2, "session": None, "fiscal": None},
    }


def test_fetch_nasdaq_dates_sin_tickers_no_llama(monkeypatch):
    def boom(**kwargs):
        raise AssertionError("no deberia crear cliente")

    monkeypatch.setattr(eds, "httpx", SimpleNamespace(AsyncClient=boom))
    assert eds.fetch_nasdaq_dates(set(), date(2026, 11, 9)) == {}


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            session.add(Tenant(id=1, external_id="t1"))
            session.flush()
            session.info["tenant_id"] = 1
            yield session
    finally:
        engine.dispose()


def _empresa(db, ticker, exchange="NYSE", currency="USD"):
    company = Company(
        ticker=ticker,
        name=f"{ticker} Inc",
        exchange=exchange,
        currency=currency,
        sector="S",
        industry="I",
        company_type="operating",
        valuation_model="standard_dcf",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.flush()
    return company


def test_refresh_sobrevive_a_yahoo_caido(db):
    _empresa(db, "AAPL")
    db.add(WatchItem(symbol="AAPL", company="AAPL Inc", tenant_id=1))
    db.commit()

    def yahoo_roto(symbols):
        raise OSError("yahoo caido")

    def nasdaq_ok(tickers, today):
        return {"AAPL": {"date": date(2026, 11, 20), "session": None, "fiscal": None}}

    resultado = eds.refresh_earnings_dates(
        db, today=date(2026, 11, 9), yahoo_fetcher=yahoo_roto, nasdaq_fetcher=nasdaq_ok
    )
    assert resultado["written"] == 1
    fila = db.query(EarningsDate).filter_by(ticker="AAPL").one()
    assert fila.event_date == date(2026, 11, 20) and fila.source == "nasdaq"


def test_followed_calendar_filtra_por_watchlist(db):
    _empresa(db, "AAPL")
    _empresa(db, "MSFT")
    db.add(WatchItem(symbol="AAPL", company="AAPL Inc", tenant_id=1))
    cartera = Portfolio(name="Main", base_currency="EUR", is_default=True, tenant_id=1)
    db.add(cartera)
    db.flush()
    msft = db.query(Company).filter_by(ticker="MSFT").one()
    db.add(
        Position(
            portfolio_id=cartera.id,
            company_id=msft.id,
            quantity=1,
            average_cost=1,
            tenant_id=1,
        )
    )
    for ticker in ("AAPL", "MSFT"):
        db.add(
            EarningsDate(
                ticker=ticker,
                event_date=date(2026, 11, 20),
                source="manual",
                source_label="Comunicado",
            )
        )
    db.commit()
    solo_watch = eds.followed_calendar(
        db, date(2026, 11, 1), date(2026, 11, 30), scope="watchlist"
    )
    tickers = {e["ticker"] for d in solo_watch["days"] for e in d["events"]}
    assert tickers == {"AAPL"}
    todo = eds.followed_calendar(db, date(2026, 11, 1), date(2026, 11, 30))
    assert {e["ticker"] for d in todo["days"] for e in d["events"]} == {"AAPL", "MSFT"}


def test_portfolio_dividend_dates_sin_cartera_y_con_ventana(db):
    assert eds.portfolio_dividend_dates(db, date(2026, 11, 1), date(2026, 11, 30)) == []
    company = _empresa(db, "AAPL")
    cartera = Portfolio(name="Main", base_currency="EUR", is_default=True, tenant_id=1)
    db.add(cartera)
    db.flush()
    db.add(
        Position(
            portfolio_id=cartera.id,
            company_id=company.id,
            quantity=10,
            average_cost=100,
            tenant_id=1,
        )
    )
    db.add(
        DividendRecord(
            company_id=company.id,
            ex_date=date(2026, 11, 10),
            pay_date=date(2026, 12, 15),  # fuera de la ventana
            amount=0.24,
            currency="USD",
            source="fmp",
            tenant_id=1,
        )
    )
    db.add(
        DividendRecord(
            company_id=company.id,
            ex_date=date(2026, 11, 20),
            pay_date=None,
            amount=0,
            currency="USD",
            source="fmp",
            tenant_id=1,
        )
    )
    db.commit()
    items = eds.portfolio_dividend_dates(db, date(2026, 11, 1), date(2026, 11, 30))
    assert len(items) == 2
    primero, segundo = items
    assert primero["kind"] == "ex_dividend" and primero["date"] == "2026-11-10"
    assert primero["detail"] == "0.24 USD por acción" and primero["status"] == "oficial"
    assert segundo["detail"] is None and segundo["kind"] == "ex_dividend"
