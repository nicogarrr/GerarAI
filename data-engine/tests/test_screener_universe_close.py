from datetime import date, timedelta
from decimal import Decimal

from app.models import MarketPrice
from app.services.screener_universe_service import universe_close_rows
from tests.test_propicks_prices import _company, _db

TODAY = date(2026, 10, 19)


def _add(db, ticker, closes, *, cik="1", last=date(2026, 10, 16), sector="Industrials"):
    c = _company(ticker)
    c.cik = cik
    c.sector = sector
    db.add(c)
    db.flush()
    for i, px in enumerate(reversed(closes)):
        db.add(MarketPrice(company_id=c.id, date=last - timedelta(days=i), close=Decimal(px),
                           adj_close=Decimal(px), source="test"))
    db.flush()
    return c


def test_rows_have_date_change_and_exclusions():
    db = _db()
    _add(db, "OKCO", ["100", "110"])
    _add(db, "LIVE", ["10", "11"])            # ya sale en vivo: excluida
    _add(db, "ZZZZ9", ["5", "6"], cik=None)   # sintetico: patron Z{3,}
    _add(db, "TESTCO", ["5", "6"], cik=None)  # sintetico: patron TEST
    _add(db, "REALNOCIK", ["20", "22"], cik=None)  # real sin CIK/ISIN: entra
    _add(db, "OLD", ["5", "6"], last=date(2026, 9, 1))  # cierre viejo: fuera
    out = universe_close_rows(db, exclude_symbols={"LIVE"}, today=TODAY)
    assert sorted(r["symbol"] for r in out["rows"]) == ["OKCO", "REALNOCIK"]
    row = next(r for r in out["rows"] if r["symbol"] == "OKCO")
    assert row["close_date"] == "2026-10-16"
    assert abs(row["change_pct"] - 10.0) < 1e-6
    assert out["total"] == 2


def test_limit_cuts_before_prev_close_queries_and_keeps_total():
    db = _db()
    for t in ("AAA", "BBB", "CCC"):
        _add(db, t, ["100", "120"], cik=None)
    out = universe_close_rows(db, exclude_symbols=set(), limit=2, today=TODAY)
    assert out["total"] == 3 and [r["symbol"] for r in out["rows"]] == ["AAA", "BBB"]
    assert all(abs(r["change_pct"] - 20.0) < 1e-6 for r in out["rows"])


def test_change_is_none_without_previous_close_and_sector_filter():
    db = _db()
    _add(db, "ONE", ["100"], sector="Energy")
    _add(db, "TWO", ["100", "90"], sector="Materials")
    out = universe_close_rows(db, exclude_symbols=set(), sector="Energy", today=TODAY)
    assert [r["symbol"] for r in out["rows"]] == ["ONE"]
    assert out["rows"][0]["change_pct"] is None
