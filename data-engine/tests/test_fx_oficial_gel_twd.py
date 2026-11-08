"""Tipos que el BCE no publica (GEL, TWD) salen del banco central emisor.

Antes (main 95a9c193d): la etapa FX solo pedia al BCE y solo para divisas de
cartera; GEL (Georgia Capital) y TWD (TSMC) quedaban sin tipo y el DCF y la
TIR de CGEO.L y TSM salian bloqueados («fx_rate:GEL/GBP», «sin tipo de cambio
USD→TWD»). Ahora: NBG para GEL y CBC para TWD, guardados con su fuente y su
fecha; si la fuente falla, la divisa sale en los errores con el motivo.
"""

import asyncio
import json
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, FinancialFact, FXRate, Portfolio
from app.services.connectors.ecb import ECBRates
from app.services.connectors.official_fx import (
    CBC_API_URL,
    CBC_DAILY_URL,
    fetch_official_quotes,
    parse_cbc_api,
    parse_cbc_daily,
    parse_nbg,
    to_base_rates,
)
from app.services.market_refresh_service import MarketRefreshService
from app.valuation.currency import resolve_fx

DAY = date(2026, 11, 6)

NBG_JSON = json.dumps(
    [
        {
            "date": "2026-11-06T00:00:00.000Z",
            "currencies": [
                {
                    "code": "AMD",
                    "quantity": 1000,
                    "rate": 7.2001,
                    "validFromDate": "2026-11-06T00:00:00.000Z",
                },
                {"code": "EUR", "quantity": 1, "rate": 2.9145, "validFromDate": "2026-11-06T00:00:00.000Z"},
                {"code": "USD", "quantity": 1, "rate": 2.5955, "validFromDate": "2026-11-06T00:00:00.000Z"},
            ],
        }
    ]
)

CBC_HTML = """<table class="rwd-table"> <tr> <th>Date</th> <th>NTD/USD</th> </tr>
<tr> <td data-th="Date"><span>2026/11/06</span></td> <td data-th="NTD/USD"><span>32.768</span></td> </tr>
<tr> <td data-th="Date"><span>2026/11/05</span></td> <td data-th="NTD/USD"><span>32.876</span></td> </tr></table>"""

CBC_API_JSON = json.dumps(
    {
        "meta": {"title": "BP01"},
        "data": {
            "dataSets": [["20261029", "32.530", "157.1"], ["20261030", "32.478", "157.55"]],
            "structure": {"Table1": [{"data": "新台幣NTD/USD"}, {"data": "日圓JPY/USD"}]},
        },
    }
)


def _fetcher(pages: dict[str, str]):
    async def fetch(url: str) -> str:
        for prefix, body in pages.items():
            if url.startswith(prefix):
                if isinstance(body, Exception):
                    raise body
                return body
        raise ValueError(f"sin pagina para {url}")

    return fetch


def test_parse_nbg_lari_per_unit():
    quotes = {q.per: q for q in parse_nbg(NBG_JSON)}
    assert set(quotes) == {"USD", "EUR"}
    assert quotes["USD"].units == Decimal("2.5955")
    assert quotes["EUR"].rate_date == DAY
    assert quotes["USD"].currency == "GEL"


def test_parse_cbc_daily_and_api():
    daily = parse_cbc_daily(CBC_HTML)
    assert [(q.rate_date, q.units) for q in daily] == [
        (date(2026, 11, 6), Decimal("32.768")),
        (date(2026, 11, 5), Decimal("32.876")),
    ]
    api = parse_cbc_api(CBC_API_JSON)
    assert api[0].rate_date == date(2026, 10, 30) and api[0].units == Decimal("32.478")
    with pytest.raises(ValueError):
        parse_cbc_daily("<html>otra cosa</html>")


def test_to_base_rates_direct_and_cross():
    quotes = parse_nbg(NBG_JSON) + parse_cbc_daily(CBC_HTML)[:1]
    rates = to_base_rates(quotes, base_currency="EUR", base_per={"USD": Decimal("0.9")}, base_per_date=DAY)
    # GEL directo contra EUR: 1 / 2,9145 EUR por lari.
    assert rates["GEL"].rate == Decimal("1") / Decimal("2.9145")
    assert rates["GEL"].source.startswith("NBG")
    # TWD cruzado: (EUR por USD del BCE) / (TWD por USD del CBC).
    assert rates["TWD"].rate == Decimal("0.9") / Decimal("32.768")
    assert "CBC" in rates["TWD"].source and "ECB" in rates["TWD"].source


def test_cbc_falls_back_to_api_and_errors_are_kept():
    quotes, errors = asyncio.run(
        fetch_official_quotes(
            {"TWD", "GEL"},
            on=DAY,
            fetcher=_fetcher({CBC_DAILY_URL: "<html>cambio de formato</html>", CBC_API_URL: CBC_API_JSON}),
        )
    )
    assert [(q.currency, q.rate_date) for q in quotes] == [("TWD", date(2026, 10, 30))]
    # GEL no se obtuvo: sale con su motivo, no desaparece.
    assert [e["currency"] for e in errors] == ["GEL"] and errors[0]["reason"]


class _ECBWithoutGelTwd:
    async def fetch(self, *, base_currency, quote_currencies):
        published = {"USD": Decimal("0.9"), "GBP": Decimal("1.15")}
        return ECBRates(rate_date=DAY, rates={c: published[c] for c in quote_currencies if c in published})


class _NoPrices:
    async def fetch(self, companies, *, as_of):
        return {}, []


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        session.info["tenant_id"] = "tenant-test"
        session.add(Portfolio(name="Main", base_currency="EUR", is_default=True))
        for ticker, ccy, unit in (("CGEO.L", "GBP", "GEL"), ("TSM", "USD", "TWD")):
            company = Company(
                ticker=ticker,
                name=ticker,
                exchange="X",
                currency=ccy,
                sector="S",
                industry="I",
                company_type="operating",
                valuation_model="unassigned",
                special_sources=[],
                special_risks=[],
                factor_tags=[],
            )
            session.add(company)
            session.flush()
            # Sin posicion: empresa solo en seguimiento.
            session.add(
                FinancialFact(
                    company_id=company.id,
                    metric="revenue",
                    value=Decimal("1"),
                    unit=unit,
                    period="2025-12-31:FY",
                )
            )
        session.commit()
        yield session


def _refresh(db, pages):
    service = MarketRefreshService(
        price_provider=_NoPrices(), fx_provider=_ECBWithoutGelTwd(), official_fx_fetcher=_fetcher(pages)
    )
    return asyncio.run(service.refresh(db, as_of=DAY))


def test_refresh_stores_official_gel_and_twd_for_watchlist_companies(db):
    result = _refresh(db, {"https://nbg.gov.ge": NBG_JSON, CBC_DAILY_URL: CBC_HTML})
    stage = next(s for s in result["stages"] if s["name"] == "update_fx")
    assert stage["errors"] == []
    rows = {r.quote_currency: r for r in db.scalars(select(FXRate)).all()}
    assert rows["GEL"].source.startswith("NBG") and rows["GEL"].rate_date == DAY
    assert rows["TWD"].source.startswith("CBC")
    # La valoracion ya convierte: GBP→GEL (CGEO.L) y USD→TWD (TSM).
    gel = resolve_fx(db, "GBP", "GEL", DAY)
    twd = resolve_fx(db, "USD", "TWD", DAY)
    assert gel is not None and abs(gel.rate - 1.15 * 2.9145) < 1e-6
    assert twd is not None and abs(twd.rate - 32.768) < 1e-6


def test_refresh_reports_official_source_failure(db):
    result = _refresh(db, {"https://nbg.gov.ge": ValueError("caida"), CBC_DAILY_URL: CBC_HTML})
    stage = next(s for s in result["stages"] if s["name"] == "update_fx")
    assert stage["status"] == "partial"
    assert [e["currency"] for e in stage["errors"]] == ["GEL"]
    assert "GEL" not in {r.quote_currency for r in db.scalars(select(FXRate)).all()}


def test_http_get_goes_through_public_fetch(monkeypatch):
    from app.services.connectors import official_fx

    calls = {}

    async def fake_fetch(url, *, timeout, headers):
        calls["url"] = url
        calls["headers"] = headers
        return b"contenido", "text/plain", url

    monkeypatch.setattr(official_fx, "fetch_public_url_async", fake_fetch)
    text = asyncio.run(official_fx._http_get("https://nbg.gov.ge/ejemplo"))
    assert text == "contenido"
    assert calls["url"] == "https://nbg.gov.ge/ejemplo"
