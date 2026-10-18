"""yahoo_chart_symbol: la clase US punto->guion vive en el conector (fuente
unica usada por extended-quote, quote, velas, dividendos y splits)."""
import asyncio

from app.services.connectors.yahoo import YahooFinanceClient, yahoo_chart_symbol


def test_us_share_class_dot_maps_to_dash():
    assert yahoo_chart_symbol("BRK.B") == "BRK-B"
    assert yahoo_chart_symbol("BF.A") == "BF-A"
    assert yahoo_chart_symbol("brk.b") == "BRK-B"  # case-insensitive


def test_everything_else_passes_untouched():
    assert yahoo_chart_symbol("BRK-B") == "BRK-B"  # ya en notacion Yahoo
    assert yahoo_chart_symbol("SAN.MC") == "SAN.MC"  # sufijo de bolsa (2 letras)
    assert yahoo_chart_symbol("ASML.AS") == "ASML.AS"
    assert yahoo_chart_symbol("BTC-USD") == "BTC-USD"
    assert yahoo_chart_symbol("AAPL") == "AAPL"
    assert yahoo_chart_symbol("GOOG") == "GOOG"


def test_chart_requests_the_dashed_symbol(monkeypatch):
    """BRK.B debe pedir a Yahoo la URL con guion (BRK.B da 404 real)."""
    requested = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"chart": {"result": [{"meta": {"symbol": "BRK-B"}}]}}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, params=None, headers=None):
            requested.append(url)
            return FakeResponse()

    monkeypatch.setattr("app.services.connectors.yahoo.httpx.AsyncClient", lambda **kw: FakeClient())
    node = asyncio.run(YahooFinanceClient().extended_chart("BRK.B"))
    assert node["meta"]["symbol"] == "BRK-B"
    assert requested and requested[0].endswith("/BRK-B")
