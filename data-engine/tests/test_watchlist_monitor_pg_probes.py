"""Integration coverage for PG probes; uses only a temporary price table."""
import os
from datetime import date
from decimal import Decimal

import pytest
import sqlalchemy as sa

from app.api.routes import watchlist as wl


def test_pg_probes_filter_invalid_prices_and_keep_empty_companies():
    url = os.environ.get("WATCHLIST_TEST_PG_URL")
    if not url:
        pytest.skip("WATCHLIST_TEST_PG_URL is required for PG integration test")
    engine = sa.create_engine(url)
    try:
        with engine.connect() as conn, conn.begin():
            conn.execute(sa.text("""
                CREATE TEMPORARY TABLE market_prices (
                    company_id integer, date date, close numeric,
                    quote_currency text
                ) ON COMMIT DROP
            """))
            conn.execute(sa.text("""
                INSERT INTO market_prices VALUES
                (1, '2026-01-01', 10, 'GBp'),
                (1, '2026-02-01', 20, 'GBp'),
                (1, '2026-03-01', 0, 'GBp'),
                (1, '2026-04-01', NULL, 'GBp'),
                (2, '2025-01-01', 30, 'USD'),
                (3, '2026-04-01', 0, 'EUR')
            """))
            params = {"ids": [1, 2, 3, 4], "cutoff": date(2026, 2, 1)}
            closes = {
                r.company_id: (r.close, r.date, r.quote_currency)
                for r in conn.execute(sa.text(wl._MONITOR_CIERRE_LATERAL_PG), params)
            }
            counts = {
                r.cid: r.n
                for r in conn.execute(sa.text(wl._MONITOR_SESIONES_LATERAL_PG), params)
            }
            assert closes == {
                1: (Decimal("20"), date(2026, 2, 1), "GBp"),
                2: (Decimal("30"), date(2025, 1, 1), "USD"),
            }
            assert counts == {1: 1, 2: 0, 3: 0, 4: 0}
            for sql in (wl._MONITOR_CIERRE_LATERAL_PG, wl._MONITOR_SESIONES_LATERAL_PG):
                assert list(conn.execute(sa.text(sql), {**params, "ids": []})) == []
    finally:
        engine.dispose()
