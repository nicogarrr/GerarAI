"""Calendario publico de IPOs de NASDAQ: formatos REALES medidos en la API.

Las filas replican lo devuelto por ``api.nasdaq.com/api/ipo/calendar`` en
octubre de 2026: ``priced.rows`` con ``pricedDate`` y ``upcoming.upcomingTable.rows``
con ``expectedPriceDate`` y rango de precio ("15.00-17.00"); meses sin
registros devuelven ``rows: null`` (codigo 1002), que NO es un fallo.
"""

import asyncio
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.services.connectors import ipo_calendar as ipo

PRICED_ROW = {
    "dealID": "1112626-119575",
    "proposedTickerSymbol": "LYCA",
    "companyName": "Lycia Therapeutics, Inc.",
    "proposedExchange": "NASDAQ Global Select",
    "proposedSharePrice": "18.00",
    "sharesOffered": "17,640,000",
    "pricedDate": "10/23/2026",
    "dollarValueOfSharesOffered": "$317,520,000",
    "dealStatus": "Priced",
}

UPCOMING_ROW = {
    "dealID": "1405733-119610",
    "proposedTickerSymbol": "ASPE",
    "companyName": "Aspen Neuroscience, Inc.",
    "proposedExchange": "NASDAQ Global Select",
    "proposedSharePrice": "15.00-17.00",
    "sharesOffered": "9,375,000",
    "expectedPriceDate": "10/30/2026",
    "dollarValueOfSharesOffered": "$183,281,250",
}


def _payload(priced=None, upcoming=None):
    return {
        "data": {
            "priced": {"rows": priced},
            "upcoming": {"upcomingTable": {"rows": upcoming}},
        }
    }


@pytest.fixture(autouse=True)
def _clear_month_cache():
    ipo._month_cache.clear()  # noqa: SLF001 - estado de proceso del conector
    yield
    ipo._month_cache.clear()  # noqa: SLF001


def test_normalize_priced_row_real_format():
    event = ipo.normalize_ipo_row(PRICED_ROW, "priced")
    assert event["symbol"] == "LYCA"
    assert event["company"] == "Lycia Therapeutics, Inc."
    assert event["exchange"] == "NASDAQ Global Select"
    assert event["date"] == "2026-10-23"
    assert event["price"] == "18.00"
    assert event["offer_amount"] == "$317,520,000"
    assert event["status"] == "priced"
    assert event["source"] == ipo.SOURCE_NASDAQ_IPO


def test_normalize_upcoming_row_keeps_range_and_expected_date():
    event = ipo.normalize_ipo_row(UPCOMING_ROW, "upcoming")
    assert event["date"] == "2026-10-30"
    assert event["price"] == "15.00-17.00"  # rango tal cual lo trae la fuente
    assert event["status"] == "upcoming"


def test_normalize_without_date_or_symbol_invents_nothing():
    row = {k: v for k, v in UPCOMING_ROW.items() if k != "expectedPriceDate"}
    row["proposedTickerSymbol"] = None
    event = ipo.normalize_ipo_row(row, "upcoming")
    assert event["date"] is None
    assert event["symbol"] is None
    assert event["company"] == "Aspen Neuroscience, Inc."


def test_payload_events_dedupes_priced_over_upcoming():
    both = [UPCOMING_ROW, {**PRICED_ROW, "dealID": UPCOMING_ROW["dealID"]}]
    events = ipo._payload_events(_payload(priced=[both[1]], upcoming=[both[0]]))
    assert len(events) == 1
    assert events[0]["status"] == "priced"


def test_payload_events_null_rows_is_empty_not_error():
    assert ipo._payload_events(_payload(priced=None, upcoming=None)) == []


def test_fetch_ipo_month_ok(monkeypatch):
    async def fake_json(url, params, client):
        assert url == ipo.IPO_URL and params["date"] == "2026-10"
        return _payload(priced=[PRICED_ROW], upcoming=[UPCOMING_ROW])

    monkeypatch.setattr(ipo, "_get_json", fake_json)
    result = asyncio.run(ipo.fetch_ipo_month(date(2026, 10, 15)))
    assert result["status"] == "ok"
    assert result["month"] == "2026-10"
    assert len(result["events"]) == 2


def test_fetch_ipo_month_degrades_to_unavailable(monkeypatch):
    async def fake_json(url, params, client):
        return None

    monkeypatch.setattr(ipo, "_get_json", fake_json)
    result = asyncio.run(ipo.fetch_ipo_month(date(2026, 10, 1)))
    assert result["status"] == "unavailable"
    assert result["events"] == []
    assert "2026-10" in result["errors"][0]


def test_fetch_ipo_calendar_combines_months_and_status(monkeypatch):
    async def fake_json(url, params, client):
        if params["date"] == "2026-10":
            return _payload(priced=[PRICED_ROW], upcoming=[UPCOMING_ROW])
        return None  # noviembre no responde

    monkeypatch.setattr(ipo, "_get_json", fake_json)
    result = asyncio.run(ipo.fetch_ipo_calendar([date(2026, 10, 29), date(2026, 11, 1)]))
    assert result["status"] == "partial"
    assert result["months"] == ["2026-10", "2026-11"]
    assert result["count"] == 2
    # Orden: por fecha; sin fecha al final
    assert [e["date"] for e in result["events"]] == ["2026-10-23", "2026-10-30"]

    async def all_down(url, params, client):
        return None

    ipo._month_cache.clear()  # noqa: SLF001 - cada escenario parte sin cache
    monkeypatch.setattr(ipo, "_get_json", all_down)
    result = asyncio.run(ipo.fetch_ipo_calendar([date(2026, 10, 1), date(2026, 11, 1)]))
    assert result["status"] == "unavailable"
    assert result["count"] == 0


def test_add_months_rolls_year():
    assert ipo.add_months(date(2026, 12, 25), 1) == date(2027, 1, 1)
    assert ipo.add_months(date(2026, 10, 29), 2) == date(2026, 12, 1)


def test_ipos_route_end_to_end(monkeypatch):
    import main
    from app.api.routes import calendar as calendar_routes

    # Fecha fija: el endpoint pide el mes en curso y el siguiente.
    monkeypatch.setattr(calendar_routes, "_madrid_today", lambda: date(2026, 10, 29))

    async def fake_calendar(months, client=None):
        assert [m.month for m in months] == [10, 11]  # mes actual + siguiente
        return {
            "status": "ok",
            "months": ["2026-10", "2026-11"],
            "count": 1,
            "events": [ipo.normalize_ipo_row(UPCOMING_ROW, "upcoming")],
            "errors": [],
        }

    monkeypatch.setattr(ipo, "fetch_ipo_calendar", fake_calendar)
    client = TestClient(main.app, raise_server_exceptions=False)
    response = client.get("/api/calendar/ipos")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["events"][0]["symbol"] == "ASPE"
