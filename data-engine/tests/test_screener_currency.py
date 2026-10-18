from app.api.routes import screeners


def test_real_rows_keep_provider_currency_and_leave_unknown_empty(monkeypatch):
    class Settings:
        finnhub_api_key = None
        screener_quote_vendor = "yahoo"

    monkeypatch.setattr(screeners, "get_settings", lambda: Settings())
    monkeypatch.setattr(screeners, "_REAL_UNIVERSE", [("AAA", "Alpha", "Technology"), ("BBB", "Beta", "Technology")])
    monkeypatch.setattr(screeners, "_load_universe_from_db", lambda: {})
    monkeypatch.setattr(screeners, "_load_screener_ratios", lambda **kwargs: {})
    monkeypatch.setattr(screeners, "_safe_fetch_quote", lambda client, symbol, vendor: {
        "price": 100, "currency": "EUR" if symbol == "AAA" else None,
        "change": None, "changePercent": None, "volume": None, "prevClose": None,
    })
    monkeypatch.setattr(screeners, "_safe_fetch_profile", lambda *args: {"name": "Company", "sector": "Technology", "currency": "USD", "exchange": "US", "marketCap": None})
    items = screeners._refetch_real_items(vendor="yahoo")
    assert {item["symbol"]: item["currency"] for item in items} == {"AAA": "EUR", "BBB": None}
