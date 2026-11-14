"""Basics exactos en lote; los alias conservan el resolver individual."""
from sqlalchemy import event

from app.api.routes.companies import companies_basics_batch
from app.services.company_resolver import resolve_company
from tests.test_companies_search_basics import _company, db  # noqa: F401


def test_exact_basics_single_query_independent_of_batch(db):
    for i in range(16):
        _company(db, f"EX{i}")
    statements = []
    def capture(*args):
        statements.append(args[2])
    event.listen(db.bind, "before_cursor_execute", capture)
    try:
        counts = []
        for n in (2, 16):
            statements.clear()
            out = companies_basics_batch(tickers=",".join(f"EX{i}" for i in range(n)), db=db)
            assert len(out.items) == n and not out.missing
            counts.append(len(statements))
        assert counts == [1, 1], counts
    finally:
        event.remove(db.bind, "before_cursor_execute", capture)


def test_exact_and_alias_keys_keep_single_resolver_policy(db):
    _company(db, "SAN", exchange="BME", currency="EUR")
    _company(db, "BRK.B")
    _company(db, "EXACT")
    requested = ["SAN.MC", "SAN", "BRK-B", "BRK.B", "EXACT", "MISSING"]
    expected = {ticker: resolve_company(db, ticker) for ticker in requested}
    out = companies_basics_batch(tickers=",".join(requested + ["exact", " "]), db=db)
    assert list(out.items) == [ticker for ticker in requested if expected[ticker] is not None]
    assert out.missing == [ticker for ticker in requested if expected[ticker] is None]
    for ticker, item in out.items.items():
        assert item.ticker == expected[ticker].ticker
    assert companies_basics_batch(tickers=" , ", db=db).items == {}
