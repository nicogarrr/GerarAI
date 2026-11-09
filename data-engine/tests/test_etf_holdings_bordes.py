"""etf_holdings (bordes): _pct inválido, filas con fecha mala o cash en los
parsers, pesos incoherentes (>105 % conserva la carga), ticker duplicado en
el CSV, cierre de recursos propios (cliente y sesión creados por refresh) y
etfs_for_tickers con conjunto vacío.

Sin red: HTTP con MockTransport o httpx.Client doblado; SQLite real para la
recarga. CSVs sintéticos.
"""

from datetime import date
from decimal import Decimal

import httpx
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.entities import Base, EtfHolding
from app.services import etf_holdings as eh

UFO_PAGE = "https://procureetfs.com/ufo/"
UFO_CSV_URL = "https://procureetfs.com/files/UFO-Holdings.csv"
NASA_PAGE = "https://temaetfs.com/nasa"
UFO_HTML = f'<html><a href="{UFO_CSV_URL}">holdings</a></html>'


def _procure_csv(pesos, fecha="10/19/2026"):
    filas = "".join(f"{fecha},UFO,T{chr(65 + i)},x,N,1,1,1,{w}%\n" for i, w in enumerate(pesos))
    return "Date,Account,StockTicker,CUSIP,SecurityName,Shares,Price,MarketValue,Weightings\n" + filas


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


# --- parsers ---------------------------------------------------------------


def test_pct_invalido_devuelve_none_y_formatos():
    assert eh._pct("no-es-un-numero", fraction=False) is None
    assert eh._pct("", fraction=False) is None
    assert eh._pct("15.9%", fraction=False) == Decimal("15.9")
    assert eh._pct("0.055", fraction=True) == Decimal("5.500")


def test_parse_procure_fecha_mala_se_salta():
    csv_texto = (
        "Date,Account,StockTicker,CUSIP,SecurityName,Shares,Price,MarketValue,Weightings\n"
        "fecha-mala,UFO,AAA,x,N,1,1,1,9.5%\n"
        "10/19/2026,UFO,BBB,x,N,1,1,1,4.0%\n"
    )
    as_of, rows = eh.parse_procure(csv_texto)
    assert as_of == date(2026, 10, 19)
    assert rows == [("BBB", Decimal("4.0"))]


def test_parse_tema_cash_fecha_mala_y_no_eeuu_se_saltan():
    csv_texto = (
        "holdings_date,ticker,cusip,proper_name,shares,market_value,percent_of_nav,is_cash,country,sector\n"
        "2026-10-16,USD,,Cash,1,1,0.01,1,,\n"
        "fecha-mala,AAA,cAAA,N,1,1,0.05,0,United States,IT\n"
        "2026-10-16,FTC,cFTC,N,1,1,0.05,0,United Kingdom,IT\n"
        "2026-10-16,BBB,cBBB,N,1,1,0.05,0,United States,IT\n"
    )
    as_of, rows = eh.parse_tema(csv_texto)
    assert as_of == date(2026, 10, 16)
    assert rows == [("BBB", Decimal("5.00"))]


# --- refresh: pesos incoherentes y duplicados -------------------------------


def _client(files):
    def handler(request):
        url = str(request.url)
        return httpx.Response(200, text=files[url]) if url in files else httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_refresh_pesos_incoherentes_conserva_la_carga():
    db = _db()
    try:
        files = {
            UFO_PAGE: UFO_HTML,
            UFO_CSV_URL: _procure_csv([16.0] * 10),  # 160 %: incoherente
            NASA_PAGE: "<html>sin enlace de holdings</html>",
        }
        out = eh.refresh_etf_holdings(db=db, client=_client(files))
        assert out == {
            "UFO": "pesos incoherentes: se conserva la carga anterior",
            "NASA": "sin enlace de holdings",
        }
        assert db.scalars(select(EtfHolding)).all() == []
    finally:
        db.close()


def test_refresh_ticker_duplicado_se_guarda_una_vez():
    db = _db()
    try:
        csv_dup = _procure_csv([1.0] * 10) + "10/19/2026,UFO,TA,x,N,1,1,1,1.0%\n"
        files = {
            UFO_PAGE: UFO_HTML,
            UFO_CSV_URL: csv_dup,
            NASA_PAGE: "<html>sin enlace de holdings</html>",
        }
        out = eh.refresh_etf_holdings(db=db, client=_client(files))
        assert out == {
            "UFO": "ok 10 holdings as_of 2026-10-19",
            "NASA": "sin enlace de holdings",
        }
        guardados = db.scalars(select(EtfHolding).where(EtfHolding.etf == "UFO")).all()
        assert len(guardados) == 10
        assert sum(1 for g in guardados if g.ticker == "TA") == 1
    finally:
        db.close()


# --- refresh: cierre de recursos propios ------------------------------------


def test_refresh_cierra_cliente_y_sesion_propios(monkeypatch):
    cerrado = {"http": False}
    real_client = httpx.Client
    inner = _client({UFO_PAGE: "<html>x</html>", NASA_PAGE: "<html>y</html>"})

    class FakeClient:
        def __init__(self, **kwargs):
            self._real = inner

        def get(self, url):
            return self._real.get(url)

        def close(self):
            cerrado["http"] = True

    import app.core.database as database

    db = _db()
    monkeypatch.setattr(eh.httpx, "Client", FakeClient)
    monkeypatch.setattr(database, "SessionLocal", lambda: db)
    assert real_client is not FakeClient

    out = eh.refresh_etf_holdings()

    assert out == {"UFO": "sin enlace de holdings", "NASA": "sin enlace de holdings"}
    assert cerrado["http"] is True
    # La sesión propia quedó cerrada (la creamos nosotros solo para inyectarla).
    assert not db.in_transaction()


# --- etfs_for_tickers --------------------------------------------------------


def test_etfs_for_tickers_conjunto_vacio():
    db = _db()
    try:
        assert eh.etfs_for_tickers(db, set()) == {}
    finally:
        db.close()
