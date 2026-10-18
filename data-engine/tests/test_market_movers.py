"""Contratos de GET /api/market/movers: frío-seguro y matemática honesta.

El endpoint nunca asume caché caliente: sin filas devuelve universo vacío
(la UI lo muestra como estado honesto) en lugar de KeyError/500.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.routes.market import market_movers
from app.models.entities import Base, Company, MarketPrice


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db: Session, ticker: str) -> Company:
    company = Company(
        ticker=ticker, name=ticker, exchange="NASDAQ", currency="USD",
        sector="S", industry="I", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.flush()
    return company


def _price(
    db: Session, company: Company, day: date, close: str, volume: int | None = 2_000_000, source: str = "yfinance"
) -> None:
    db.add(MarketPrice(
        company_id=company.id, date=day, open=Decimal(close),
        high=Decimal(close), low=Decimal(close), close=Decimal(close),
        adj_close=Decimal(close), volume=volume, source=source,
    ))
    db.flush()


def test_cold_start_returns_empty_universe_without_errors(db: Session):
    out = market_movers(db, 10)
    assert out["universe"] == 0
    assert out["as_of"] is None
    assert out["gainers"] == [] and out["losers"] == [] and out["most_active"] == []


def test_change_math_and_sorting(db: Session):
    aaa = _company(db, "AAA")  # +10%
    _price(db, aaa, date(2026, 9, 21), "100", volume=2_000_000)
    _price(db, aaa, date(2026, 9, 22), "110", volume=2_000_000)
    bbb = _company(db, "BBB")  # -20%, más activa
    _price(db, bbb, date(2026, 9, 21), "100", volume=9_000_000)
    _price(db, bbb, date(2026, 9, 22), "80", volume=9_000_000)
    ccc = _company(db, "CCC")  # +5%
    _price(db, ccc, date(2026, 9, 21), "100", volume=1_500_000)
    _price(db, ccc, date(2026, 9, 22), "105", volume=1_500_000)

    out = market_movers(db, 10)
    assert out["universe"] == 3
    assert out["as_of"] == "2026-09-22"
    assert [m["ticker"] for m in out["gainers"]] == ["AAA", "CCC", "BBB"]
    assert out["gainers"][0]["change_pct"] == pytest.approx(10.0)
    assert [m["ticker"] for m in out["losers"]] == ["BBB", "CCC", "AAA"]
    assert out["losers"][0]["change_pct"] == pytest.approx(-20.0)
    assert out["most_active"][0]["ticker"] == "BBB"


def test_single_price_row_reports_unknown_change_instead_of_zero(db: Session):
    """Con un solo cierre no hay cambio medible: None (la UI muestra "—"),
    nunca un 0.0% que aparenta un dato inexistente. La empresa sigue
    contando en el universo pero no entra en subidas/bajadas."""
    solo = _company(db, "SOLO")
    _price(db, solo, date(2026, 9, 22), "50", volume=2_000_000)
    out = market_movers(db, 10)
    assert out["universe"] == 1
    assert out["gainers"] == [] and out["losers"] == []
    assert out["most_active"][0]["ticker"] == "SOLO"


def test_limit_slices_lists(db: Session):
    for i in range(5):
        company = _company(db, f"L{i:02d}")
        _price(db, company, date(2026, 9, 21), "100")
        _price(db, company, date(2026, 9, 22), str(100 + i))
    out = market_movers(db, 2)
    assert len(out["gainers"]) == 2 and len(out["losers"]) == 2 and len(out["most_active"]) == 2
    assert out["universe"] == 5


def test_unknown_volume_is_null_and_out_of_most_active(db: Session):
    """Volumen desconocido: null honesto, fuera del ranking de "mas activas".

    Un 0 fabricado coronaba al ticker como el MENOS activo con un dato que
    no existe y ensuciaba la tabla de "Mas activas" con ceros.
    """
    known = _company(db, "KVOL")
    unknown = _company(db, "UVOL")
    day = date(2026, 9, 25)
    prev = date(2026, 9, 24)
    # Dos cierres por empresa para que el cambio sea medible; con el suelo de
    # liquidez, el volumen desconocido si las expulsa (negociacion no medible).
    _price(db, known, prev, "90", volume=4_000_000)
    _price(db, known, day, "100", volume=5_000_000)
    _price(db, unknown, prev, "90", volume=None)
    _price(db, unknown, day, "100", volume=None)

    out = market_movers(db, 10)

    # Sin volumen la negociacion no es medible: UVOL tampoco supera el suelo
    # de liquidez y queda fuera de subidas/bajadas (declarado, nunca colado).
    rows = {row["ticker"]: row for section in ("gainers", "losers") for row in out[section]}
    assert rows["KVOL"]["volume"] == 5_000_000
    assert "UVOL" not in rows
    assert out["excluded_illiquid"] == 1
    assert out["universe"] == 2
    most_active_tickers = [row["ticker"] for row in out["most_active"]]
    assert "KVOL" in most_active_tickers
    assert "UVOL" not in most_active_tickers


def test_stale_company_stays_in_universe_but_out_of_rankings(db: Session):
    """F9/F10: el ranking compara la ultima sesion comun. Una empresa con
    ultimo cierre viejo sigue contando en el universo (y se declara en
    excluded_not_comparable) pero no entra en subidas/bajadas/activas con una
    variacion de otra epoca presentada como la de hoy."""
    fresh = _company(db, "FRESH")
    _price(db, fresh, date(2026, 9, 21), "100")
    _price(db, fresh, date(2026, 9, 22), "101")
    stale = _company(db, "STALE")
    _price(db, stale, date(2026, 8, 20), "50")
    _price(db, stale, date(2026, 8, 21), "55")

    out = market_movers(db, 10)
    tickers = {m["ticker"] for m in out["gainers"] + out["losers"] + out["most_active"]}
    assert out["universe"] == 2
    assert out["session_date"] == "2026-09-22"
    assert out["excluded_not_comparable"] == 1
    assert "STALE" not in tickers
    assert "FRESH" in tickers


def test_gap_between_closes_is_not_a_one_session_change(db: Session):
    """IBRX (F9): si el cierre previo no es el de la sesion inmediatamente
    anterior, el cambio seria de varios dias. Se queda en None, no +22 %."""
    base = [_company(db, f"B{i}") for i in range(3)]
    for c in base:
        for day in (date(2026, 9, 30), date(2026, 10, 1), date(2026, 10, 2)):
            _price(db, c, day, "10")
    gapped = _company(db, "GAP")
    _price(db, gapped, date(2026, 9, 30), "100")
    _price(db, gapped, date(2026, 10, 2), "130")

    out = market_movers(db, 10)
    assert out["session_date"] == "2026-10-02"
    assert "GAP" not in {m["ticker"] for m in out["gainers"] + out["losers"]}
    gap_row = next(m for m in out["most_active"] if m["ticker"] == "GAP")
    assert gap_row["change_pct"] is None


def test_single_bar_company_keeps_null_change(db: Session):
    """Una sola barra = sin cambio medible de verdad: None (la UI muestra -),
    y no rompe el universo."""
    one = _company(db, "ONE")
    _price(db, one, date(2026, 9, 22), "42")

    out = market_movers(db, 10)
    assert out["universe"] == 1
    assert out["gainers"] == [] and out["losers"] == []
    mover = next(m for m in out["most_active"] if m["ticker"] == "ONE")
    assert mover["change_pct"] is None


def test_bulk_load_day_does_not_freeze_the_session(db: Session):
    """Una carga masiva puntual no puede dejar como unica sesion valida su fecha.

    El 28/9 tiene 20 empresas y los dias siguientes 4: con el maximo como
    referencia solo contaba el 28/9 y todo el ranking salia con fecha vieja y
    cambio N/D. Con la mediana, la sesion es la ultima laborable real.
    """
    bulk = [_company(db, f"B{i}") for i in range(20)]
    for company in bulk:
        _price(db, company, date(2026, 9, 28), "50", volume=0)
    daily = bulk[:4]
    for day, close in ((date(2026, 9, 29), "51"), (date(2026, 9, 30), "52"),
                       (date(2026, 10, 1), "53"), (date(2026, 10, 2), "54")):
        for company in daily:
            _price(db, company, day, close, volume=2_000_000)

    out = market_movers(db, 10)

    assert out["session_date"] == "2026-10-02"
    assert {row["ticker"] for row in out["gainers"]} == {c.ticker for c in daily}
    assert all(row["change_pct"] is not None for row in out["gainers"])


def test_zero_volume_is_unknown_not_a_ranked_value(db: Session):
    """Volumen 0 de la fuente = dato ausente (None). Con el suelo de liquidez,
    negociacion no medible = fuera de TODOS los rankings, declarado en
    excluded_illiquid; nunca entra con un dato supuesto."""
    company = _company(db, "ZVOL")
    _price(db, company, date(2026, 9, 24), "90", volume=0)
    _price(db, company, date(2026, 9, 25), "100", volume=0)

    out = market_movers(db, 10)

    assert out["most_active"] == []
    assert out["gainers"] == [] and out["losers"] == []
    assert out["excluded_illiquid"] == 1
    assert out["universe"] == 1


def test_changes_endpoint_uses_same_formula_as_movers(db: Session):
    from app.api.routes.market import market_changes

    aaa = _company(db, "AAA")
    _price(db, aaa, date(2026, 9, 21), "100")
    _price(db, aaa, date(2026, 9, 22), "100.45")
    solo = _company(db, "SOLO")  # un unico cierre: sin variacion medible
    _price(db, solo, date(2026, 9, 22), "50")

    changes = market_changes("aaa, solo, nope", db)
    movers = {m["ticker"]: m for m in market_movers(db, 25)["gainers"]}

    assert changes["items"]["AAA"]["change_pct"] == movers["AAA"]["change_pct"] == 0.45
    assert changes["items"]["AAA"]["previous_close"] == 100.0
    assert changes["items"]["SOLO"]["change_pct"] is None
    assert "NOPE" not in changes["items"]


def test_spot_snapshots_are_not_official_closes(db: Session):
    """Una foto spot (intradia/Finnhub) nunca es el cierre previo: AAPL daba
    +0,45 % comparando contra una foto y +0,43 % contra el cierre oficial."""
    from app.api.routes.market import market_changes

    aapl = _company(db, "AAPL")
    _price(db, aapl, date(2026, 10, 14), "340.00")
    _price(db, aapl, date(2026, 10, 15), "342.00")
    _price(db, aapl, date(2026, 10, 16), "343.46")
    # Foto spot del 16 posterior a la barra oficial y foto intradia del 15:
    # no pueden sustituir a los cierres oficiales.
    snap = _company(db, "SNAP")
    _price(db, snap, date(2026, 10, 15), "10", source="yahoo_finance_intraday")
    _price(db, snap, date(2026, 10, 16), "12", source="Finnhub")

    out = market_movers(db, 10)
    tickers = [m["ticker"] for m in out["gainers"]]
    assert "SNAP" not in tickers
    assert out["gainers"][0]["change_pct"] == 0.43
    assert market_changes("SNAP", db)["items"] == {}


def test_changes_flat_close_is_zero_not_missing_and_eur_listing(db: Session):
    """AENA (EUR, .MC): cierres oficiales 25,70 y 25,70 son 0,00 %, un dato.
    La ficha mostraba -0,08 % contra una cotizacion que no era el cierre."""
    from app.api.routes.market import market_changes

    aena = _company(db, "AENA")
    aena.exchange = "BME"
    aena.currency = "EUR"
    _price(db, aena, date(2026, 10, 15), "25.70")
    _price(db, aena, date(2026, 10, 16), "25.70")

    item = market_changes("AENA", db)["items"]["AENA"]
    assert item["change_pct"] == 0.0
    assert item["price"] == 25.7 and item["previous_close"] == 25.7
    assert item["date"] == "2026-10-16" and item["previous_date"] == "2026-10-15"


def test_microcap_penny_stock_out_of_gainers_but_in_universe(db: Session):
    """Una microcap de 2 $ con +80 % es un movimiento real en el dato pero no
    operable: fuera de Subidas por el suelo de precio (5), contada en el
    universo y en excluded_illiquid."""
    penny = _company(db, "PENNY")
    _price(db, penny, date(2026, 9, 21), "1.00", volume=50_000_000)
    _price(db, penny, date(2026, 9, 22), "1.80", volume=50_000_000)
    big = _company(db, "BIG")
    _price(db, big, date(2026, 9, 21), "100", volume=2_000_000)
    _price(db, big, date(2026, 9, 22), "110", volume=2_000_000)

    out = market_movers(db, 10)

    assert out["universe"] == 2
    assert out["excluded_illiquid"] == 1
    assert [m["ticker"] for m in out["gainers"]] == ["BIG"]
    assert [m["ticker"] for m in out["most_active"]][0] == "BIG"


def test_low_turnover_out_of_rankings(db: Session):
    """Precio suficiente pero negociacion de la sesion < 1 M: fuera tambien
    (una orden pequena mueve el precio)."""
    thin = _company(db, "THIN")
    _price(db, thin, date(2026, 9, 21), "100", volume=5_000)
    _price(db, thin, date(2026, 9, 22), "120", volume=5_000)
    liquid = _company(db, "LIQ")
    _price(db, liquid, date(2026, 9, 21), "100", volume=2_000_000)
    _price(db, liquid, date(2026, 9, 22), "105", volume=2_000_000)

    out = market_movers(db, 10)

    assert out["excluded_illiquid"] == 1
    assert [m["ticker"] for m in out["gainers"]] == ["LIQ"]
    assert "THIN" not in {m["ticker"] for m in out["losers"] + out["most_active"]}


def test_payload_declares_liquidity_floor_and_last_registered_at(db: Session):
    company = _company(db, "ONE")
    _price(db, company, date(2026, 9, 21), "100")
    _price(db, company, date(2026, 9, 22), "101")

    out = market_movers(db, 10)

    assert out["liquidity_floor"] == {"min_price": 5.0, "min_turnover": 1_000_000.0}
    assert out["excluded_illiquid"] == 0
    assert out["last_registered_at"] is not None


def test_cold_start_declares_filter_and_empty_rankings(db: Session):
    out = market_movers(db, 10)
    assert out["excluded_illiquid"] == 0
    assert out["liquidity_floor"]["min_price"] == 5.0
    assert out["last_registered_at"] is None

def test_ticker_close_change_uses_official_consecutive_sessions(db: Session):
    from app.services.market_change import ticker_close_change

    aaa = _company(db, "AAA")
    bbb = _company(db, "BBB")
    for company in (aaa, bbb):
        _price(db, company, date(2026, 9, 21), "100")
    _price(db, aaa, date(2026, 9, 22), "110")
    _price(db, bbb, date(2026, 9, 22), "90")
    info = ticker_close_change(db, aaa.id)
    assert info is not None
    assert info["date"] == "2026-09-22" and info["previous_date"] == "2026-09-21"
    assert info["change"] == pytest.approx(10) and info["change_percent"] == pytest.approx(10)
    assert ticker_close_change(db, bbb.id)["change_percent"] == pytest.approx(-10)


def test_ticker_close_change_none_without_two_official_closes(db: Session):
    from app.services.market_change import ticker_close_change

    aaa = _company(db, "AAA")
    other = _company(db, "OTH")
    _price(db, other, date(2026, 9, 21), "100")
    _price(db, other, date(2026, 9, 22), "101")
    # one official close only
    _price(db, aaa, date(2026, 9, 22), "110")
    assert ticker_close_change(db, aaa.id) is None
    # a non-official intraday snapshot never counts as a close
    _price(db, aaa, date(2026, 9, 21), "50", source="finnhub")
    assert ticker_close_change(db, aaa.id) is None


def test_ticker_close_change_none_when_previous_session_is_not_adjacent(db: Session):
    from app.services.market_change import ticker_close_change

    aaa = _company(db, "AAA")
    other = _company(db, "OTH")
    for day in (date(2026, 9, 21), date(2026, 9, 22)):
        _price(db, other, day, "100")
    _price(db, aaa, date(2026, 9, 18), "100")
    _price(db, aaa, date(2026, 9, 22), "110")
    assert ticker_close_change(db, aaa.id) is None


def test_ticker_close_change_none_when_last_close_is_stale(db: Session):
    from app.services.market_change import ticker_close_change

    aaa = _company(db, "AAA")
    other = _company(db, "OTH")
    for day in (date(2026, 9, 21), date(2026, 9, 22)):
        _price(db, other, day, "100")
    _price(db, aaa, date(2026, 9, 17), "100")
    _price(db, aaa, date(2026, 9, 18), "110")
    assert ticker_close_change(db, aaa.id) is None


def _quote(session: str):
    from app.services.extended_quote_service import ExtendedQuote

    return ExtendedQuote(ticker="AAA", status="available", session=session, price=110.0, fetched_at=1)


def test_extended_quote_route_adds_official_close_change_only_when_closed(db: Session, monkeypatch):
    import asyncio

    from app.api.routes import companies as routes

    aaa = _company(db, "AAA")
    for day, close in ((date(2026, 9, 21), "100"), (date(2026, 9, 22), "110")):
        _price(db, aaa, day, close)

    async def closed(_ticker):
        return _quote("cerrado")

    async def live(_ticker):
        return _quote("regular")

    async def inline(fn):  # in-memory sqlite cannot cross threads
        return fn()

    monkeypatch.setattr(routes, "run_in_threadpool", inline)
    monkeypatch.setattr(routes.extended_quote_service, "get", closed)
    out = asyncio.run(routes.company_extended_quote("AAA", db))
    assert out.change is None and out.change_percent is None  # Yahoo-based fields untouched
    assert out.close_change_percent == pytest.approx(10)
    assert out.close_change_date == "2026-09-22" and out.close_change_previous_date == "2026-09-21"

    monkeypatch.setattr(routes.extended_quote_service, "get", live)
    out = asyncio.run(routes.company_extended_quote("AAA", db))
    assert out.close_change_percent is None


def test_extended_quote_route_survives_db_failure(db: Session, monkeypatch):
    import asyncio

    from app.api.routes import companies as routes

    async def closed(_ticker):
        return _quote("cerrado")

    def boom(*_a, **_k):
        raise RuntimeError("db down")

    async def inline(fn):
        return fn()

    monkeypatch.setattr(routes, "run_in_threadpool", inline)
    monkeypatch.setattr(routes.extended_quote_service, "get", closed)
    monkeypatch.setattr(routes, "resolve_company", boom)
    out = asyncio.run(routes.company_extended_quote("AAA", db))
    assert out.price == 110.0 and out.close_change_percent is None
