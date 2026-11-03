"""_prior_closes: la sonda LATERAL de PostgreSQL devuelve lo mismo que la ventana.

La prueba de PostgreSQL usa solo una tabla temporal ``market_prices`` (se
salta sin ``PERF_TEST_PG_URL`` / ``WATCHLIST_TEST_PG_URL``); la de SQLite
compara la ventana portable con un calculo de referencia en Python.
"""
import os
import random
from datetime import date, timedelta
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.services import portfolio_intelligence_service as svc

_COLUMNS = "id integer primary key, company_id integer not null, date date not null, adj_close numeric(20,6)"


def _rows(seed: int = 7) -> list[tuple[int, int, date, Decimal | None]]:
    rng = random.Random(seed)
    rows: list[tuple[int, int, date, Decimal | None]] = []
    next_id = 1
    start = date(2019, 1, 1)
    for company_id in range(1, 41):
        days = sorted(rng.sample(range(0, 2500), rng.randint(0, 60)))
        for offset in days:
            adj = None if rng.random() < 0.1 else Decimal(f"{rng.uniform(1, 500):.6f}")
            rows.append((next_id, company_id, start + timedelta(days=offset), adj))
            next_id += 1
    rng.shuffle(rows)
    return rows


def _reference(rows, company_ids, cutoff):
    best: dict[int, tuple] = {}
    for row_id, company_id, day, adj in rows:
        if company_id not in company_ids or day >= cutoff:
            continue
        key = (day, row_id)
        if company_id not in best or key > best[company_id][0]:
            best[company_id] = (key, (company_id, day, adj))
    return {cid: value for cid, (_key, value) in best.items()}


_SIX = Decimal("0.000001")


def _as_tuples(result):
    return {
        cid: (row.company_id, row.date, None if row.adj_close is None else Decimal(str(row.adj_close)).quantize(_SIX))
        for cid, row in result.items()
    }


def _cases():
    ids = list(range(1, 46))  # 41..45 sin precios
    return [
        (ids, date(2021, 6, 30)),
        (ids, date(2019, 1, 1)),  # nada antes del corte
        (ids, date(2030, 1, 1)),  # todo antes del corte
        ([3, 3, 7, 44], date(2022, 3, 15)),  # ids repetidos y sin precios
    ]


def test_window_path_matches_reference_on_sqlite():
    engine = sa.create_engine("sqlite://")
    rows = _rows()
    with engine.begin() as conn:
        conn.execute(sa.text(f"CREATE TABLE market_prices ({_COLUMNS})"))
        conn.execute(
            sa.text("INSERT INTO market_prices VALUES (:id, :cid, :d, :a)"),
            [{"id": r[0], "cid": r[1], "d": r[2].isoformat(), "a": None if r[3] is None else str(r[3])} for r in rows],
        )
    with Session(engine) as db:
        for company_ids, cutoff in _cases():
            got = _as_tuples(svc._prior_closes(db, company_ids, cutoff))
            assert got == _reference(rows, set(company_ids), cutoff)
        assert svc._prior_closes(db, [], date(2022, 1, 1)) == {}


def test_lateral_probe_matches_window_on_postgres():
    url = os.environ.get("PERF_TEST_PG_URL") or os.environ.get("WATCHLIST_TEST_PG_URL")
    if not url:
        pytest.skip("PERF_TEST_PG_URL is required for PG integration test")
    engine = sa.create_engine(url)
    rows = _rows(11)
    try:
        with engine.connect() as conn, conn.begin():
            conn.execute(sa.text(f"CREATE TEMPORARY TABLE market_prices ({_COLUMNS}) ON COMMIT DROP"))
            conn.execute(sa.text("CREATE UNIQUE INDEX ON market_prices (company_id, date)"))
            conn.execute(
                sa.text("INSERT INTO market_prices VALUES (:id, :cid, :d, :a)"),
                [{"id": r[0], "cid": r[1], "d": r[2], "a": r[3]} for r in rows],
            )
            db = Session(bind=conn)
            assert db.get_bind().dialect.name == "postgresql"
            for company_ids, cutoff in _cases():
                lateral = _as_tuples(svc._prior_closes(db, company_ids, cutoff))
                window = _as_tuples(svc._prior_closes(db, company_ids, cutoff, lateral=False))
                assert lateral == window == _reference(rows, set(company_ids), cutoff)
            db.close()
    finally:
        engine.dispose()
