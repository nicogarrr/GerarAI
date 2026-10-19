from datetime import date

from app.services.connectors.yahoo_earnings import _estimate_from_calendar


def test_estimate_takes_min_future_date():
    cal = {"Earnings Date": [date(2027, 1, 12)]}
    assert _estimate_from_calendar(cal, date(2026, 10, 19)) == date(2027, 1, 12)


def test_estimate_ignores_past_and_non_dict():
    cal = {"Earnings Date": [date(2026, 10, 13), date(2027, 1, 12)]}
    assert _estimate_from_calendar(cal, date(2026, 10, 19)) == date(2027, 1, 12)
    assert _estimate_from_calendar(None, date(2026, 10, 19)) is None
    assert _estimate_from_calendar({"Earnings Date": []}, date(2026, 10, 19)) is None
    assert _estimate_from_calendar({"Earnings Date": ["no-es-fecha"]}, date(2026, 10, 19)) is None


def test_fetch_omits_failures_and_respects_deadline(monkeypatch):
    import app.services.connectors.yahoo_earnings as mod

    class FakeTicker:
        def __init__(self, symbol):
            if symbol == "BOOM":
                raise RuntimeError("yahoo down")
            self.calendar = {"Earnings Date": [date(2027, 1, 12)]} if symbol == "UNH" else {}

    monkeypatch.setattr("yfinance.Ticker", FakeTicker)
    found = mod.fetch_next_earnings_dates(["UNH", "BOOM", "NONE"], today=date(2026, 10, 19))
    assert found == {"UNH": "2027-01-12"}

    # Deadline ya agotado: no consulta nada y devuelve lo encontrado (nada).
    found = mod.fetch_next_earnings_dates(["UNH"], today=date(2026, 10, 19), deadline_monotonic=0.0)
    assert found == {}
