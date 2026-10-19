"""Holdings oficiales de ETFs: parseo, recarga segura y vinculo por peso/fecha."""

from datetime import date

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, EtfHolding
from app.services import etf_holdings as eh
from app.services import news_related_tickers as nrt

PROCURE = (
    "Date,Account,StockTicker,CUSIP,SecurityName,Shares,Price,MarketValue,Weightings\n"
    + "".join(f"10/19/2026,UFO,T{c},x,N,1,1,1,{w}%\n" for c, w in zip("ABCDEFGHIJK", [15.9, 5.4, 4, 3, 2.5, 2, 1.5, 1, 1, 1, 1]))
    + "10/19/2026,UFO,Cash&Other,,Cash,1,1,1,0.5%\n"
)
TEMA = (
    "holdings_date,ticker,cusip,proper_name,shares,market_value,percent_of_nav,is_cash,country,sector\n"
    "2026-10-16,SPACEX SPV,SPACEX SPV,SPV,1,1,0.18,0,,\n"
    "2026-10-16,FTC LN,,Filtronic,1,1,0.05,0,United Kingdom,IT\n"
    "2026-10-16,USD,,Cash,1,1,0.01,1,,\n"
    + "".join(f"2026-10-16,N{c},c{c},N,1,1,{w},0,United States,IT\n" for c, w in zip("ABCDEFGHIJK", [0.1, 0.09, 0.055, 0.05, 0.04, 0.03, 0.03, 0.02, 0.02, 0.01, 0.01]))
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def test_parsers_keep_only_listed_equities_with_weight_and_date():
    as_of, rows = eh.parse_procure(PROCURE)
    assert as_of == date(2026, 10, 19) and ("TA", eh.Decimal("15.9")) in rows
    assert all(t != "Cash&Other" for t, _ in rows)
    as_of, rows = eh.parse_tema(TEMA)
    tickers = {t for t, _ in rows}
    assert as_of == date(2026, 10, 16)
    assert tickers >= {"NA", "NB", "NC"} and not tickers & {"SPACEX SPV", "FTC LN", "USD"}
    assert dict(rows)["NC"] == eh.Decimal("5.5")  # fraccion -> %


def _client(files: dict[str, str]):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        return httpx.Response(200, text=files[url]) if url in files else httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_refresh_replaces_and_keeps_previous_on_failure(db):
    files = {
        "https://procureetfs.com/ufo/": '<a href="https://procureetfs.com/x/UFO-JP-Holdings-Oct-19-2026.csv">',
        "https://procureetfs.com/x/UFO-JP-Holdings-Oct-19-2026.csv": PROCURE,
        "https://temaetfs.com/nasa": '<a href="https://temaetfs.com/h/NASA-holdings-10162026.csv">',
        "https://temaetfs.com/h/NASA-holdings-10162026.csv": TEMA,
    }
    out = eh.refresh_etf_holdings(db, _client(files))
    assert out["UFO"].startswith("ok") and out["NASA"].startswith("ok")
    assert db.scalar(select(EtfHolding.weight_pct).where(EtfHolding.etf == "UFO", EtfHolding.ticker == "TA")) == eh.Decimal("15.9")
    # el emisor cae: se conserva lo anterior
    out = eh.refresh_etf_holdings(db, _client({}))
    assert "se conserva" in out["UFO"] or "error" in out["UFO"]
    assert db.scalar(select(EtfHolding).where(EtfHolding.etf == "UFO")) is not None
    # fichero truncado (<10 filas): no sustituye
    files["https://procureetfs.com/x/UFO-JP-Holdings-Oct-19-2026.csv"] = "\n".join(PROCURE.splitlines()[:4])
    out = eh.refresh_etf_holdings(db, _client(files))
    assert "incompleto" in out["UFO"]
    assert len(db.scalars(select(EtfHolding).where(EtfHolding.etf == "UFO")).all()) >= 10


def test_etf_links_need_weight_and_fresh_holdings(db):
    db.add_all([
        EtfHolding(etf="NASA", ticker="ASTS", weight_pct=5.5, as_of=date(2026, 10, 16), source_url="u"),
        EtfHolding(etf="UFO", ticker="ASTS", weight_pct=1.0, as_of=date(2026, 10, 19), source_url="u"),
        EtfHolding(etf="UFO", ticker="OLD", weight_pct=9, as_of=date(2026, 7, 1), source_url="u"),
    ])
    db.flush()
    got = eh.etfs_for_tickers(db, {"ASTS", "OLD"}, today=date(2026, 10, 19))
    assert [e["ticker"] for e in got["ASTS"]] == ["NASA"]  # UFO 1 % < 2 %
    assert "OLD" not in got  # holdings de >45 dias


def test_news_strip_includes_etf_for_primary_even_without_other_tickers(db):
    nrt._INDEX_CACHE.update(at=0.0, value=None)
    asts = Company(
        ticker="ASTS", name="AST SpaceMobile", exchange="NASDAQ", currency="USD",
        sector="Tech", industry="Tech", company_type="holding", valuation_model="unassigned",
        special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(asts)
    db.flush()
    from datetime import date as d
    today = d.today()
    db.add(EtfHolding(etf="NASA", ticker="ASTS", weight_pct=5.5, as_of=today, source_url="u"))
    db.flush()
    out = nrt.related_for_events(db, [(1, asts, "AST SpaceMobile wins contract")])
    assert [e["ticker"] for e in out[1]] == ["ASTS", "NASA"]
    assert out[1][1]["kind"] == "etf" and out[1][1]["weight_pct"] == 5.5
    assert out[1][0]["primary"] is True
