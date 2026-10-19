import asyncio

from app.api.routes import companies as routes
from app.services.extended_quote_service import ExtendedQuote


class _Svc:
    def __init__(self, quotes):
        self.quotes = quotes

    async def get(self, ticker):
        return self.quotes.get(ticker, ExtendedQuote(ticker=ticker, fetched_at=1))


def _q(ticker, currency="CAD", price=4.05):
    return ExtendedQuote(ticker=ticker, status="available", price=price, currency=currency, session="cerrado", fetched_at=1)


def test_krknf_falls_back_to_reviewed_listing(monkeypatch):
    monkeypatch.setattr(routes, "extended_quote_service", _Svc({"PNG.V": _q("PNG.V")}))
    out = asyncio.run(routes.company_extended_quote("KRKNF", db=None))
    assert out.ticker == "KRKNF" and out.price == 4.05 and out.currency == "CAD"
    assert "PNG.V" in out.source and "CAD" in out.source
    assert out.close_change is None


def test_fallback_rejects_wrong_currency(monkeypatch):
    monkeypatch.setattr(routes, "extended_quote_service", _Svc({"PNG.V": _q("PNG.V", currency="USD")}))
    out = asyncio.run(routes.company_extended_quote("KRKNF", db=None))
    assert out.status == "unavailable"


def test_unmapped_ticker_stays_unavailable(monkeypatch):
    monkeypatch.setattr(routes, "extended_quote_service", _Svc({}))
    out = asyncio.run(routes.company_extended_quote("ZZZZ", db=None))
    assert out.status == "unavailable"
