"""Filas crudas de IBKR: se guardan todas, pero la carga de cartera lee solo las necesarias.

Antes, ``reconcile_ibkr_costs`` (cada GET de posiciones) cargaba TODAS las filas
OpenPosition del tenant: con un sync diario, cientos o miles de extractos viejos
por carga. Ahora lee solo las del dia (``report_date``) y ticker de cada
posicion, con el indice ``ix_ibkr_raw_rows_snapshot``. Ninguna fila se borra.
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text

from app.models import IbkrRawRow, Position
from app.models.entities import ibkr_raw_row_keys
from app.services.ibkr_cost_reconciliation import reconcile_ibkr_costs
from app.services.ibkr_import_service import IBKRImportService

from .test_ibkr_cost_canary import db, xml  # noqa: F401 - fixture

HISTORY = 300
DATA_ENGINE_DIR = Path(__file__).resolve().parents[1]


def _add_history(session, days: int) -> None:
    start = date(2026, 10, 26)
    for i in range(days):
        day = start - timedelta(days=i)
        for symbol in ("BABA", "MSFT"):
            session.add(IbkrRawRow(
                account_id="U1", section="OpenPositions", path="OpenPositions/OpenPosition",
                row_hash=f"hist-{symbol}-{i}",
                payload={"accountId": "U1", "symbol": symbol, "position": "6.0572", "costBasisPrice": "108.396746",
                         "currency": "USD", "reportDate": day.isoformat()},
            ))
    session.flush()


def _loaded_raw_rows(session, positions) -> tuple[int, dict]:
    loaded = []

    def on_load(target, _context):
        loaded.append(target.id)

    event.listen(IbkrRawRow, "load", on_load)
    try:
        session.expire_all()
        result = reconcile_ibkr_costs(session, positions)
    finally:
        event.remove(IbkrRawRow, "load", on_load)
    return len(loaded), result


def test_portfolio_load_reads_only_the_snapshot_rows_it_needs(db):  # noqa: F811
    IBKRImportService().import_flex_xml(db, xml())
    position = db.query(Position).one()
    before_count, before = _loaded_raw_rows(db, [position])
    _add_history(db, HISTORY)
    assert db.query(IbkrRawRow).count() >= 2 * HISTORY  # todo se conserva
    after_count, after = _loaded_raw_rows(db, [position])
    # Mismo veredicto, y la lectura no crece con el historico: antes cargaba
    # 1 + 2*HISTORY filas (601), ahora solo el extracto del dia de la posicion.
    assert after == before
    assert before_count == 1
    assert after_count == 1, f"cargo {after_count} filas crudas para una posicion"


def test_keys_follow_the_reconciliation_parse():
    assert ibkr_raw_row_keys({"symbol": "BABA", "reportDate": "2026-10-27"}) == ("BABA", date(2026, 10, 27))
    assert ibkr_raw_row_keys({"symbol": "BABA", "reportDate": "20261027"}) == ("BABA", date(2026, 10, 27))
    assert ibkr_raw_row_keys({"asOfDate": "20261027;153000"}) == (None, date(2026, 10, 27))
    assert ibkr_raw_row_keys({"symbol": "", "reportDate": "27/10/2026"}) == (None, None)
    assert ibkr_raw_row_keys(None) == (None, None)


def test_insert_fills_keys_from_payload(db):  # noqa: F811
    IBKRImportService().import_flex_xml(db, xml())
    row = db.query(IbkrRawRow).filter(IbkrRawRow.path == "OpenPosition").one()
    assert (row.symbol, row.report_date) == ("BABA", date(2026, 10, 27))
    assert row.payload["reportDate"] == "2026-10-27"


def _alembic(database_url: str, *args: str) -> None:
    result = subprocess.run([sys.executable, "-m", "alembic", *args], cwd=DATA_ENGINE_DIR,
                            env={**os.environ, "DATABASE_URL": database_url},
                            capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stderr[-2000:]


def test_migration_0100_backfills_keys_and_downgrade_keeps_every_row(tmp_path: Path) -> None:
    url = f"sqlite:///{(tmp_path / 'm.db').as_posix()}"
    _alembic(url, "upgrade", "0099_paper_trade_thesis_version")
    engine = create_engine(url)
    try:
        with engine.begin() as conn:
            for i, payload in enumerate([
                '{"symbol": "BABA", "reportDate": "2026-10-27"}',
                '{"symbol": "MSFT", "asOfDate": "20261026"}',
                '{"currency": "USD"}',
            ]):
                conn.execute(text(
                    "INSERT INTO ibkr_raw_rows (section, path, row_hash, payload, created_at, updated_at) "
                    "VALUES ('OpenPositions', 'OpenPosition', :h, :p, '2026-10-29', '2026-10-29')"
                ), {"h": f"h{i}", "p": payload})
        _alembic(url, "upgrade", "0100_ibkr_raw_row_snapshot_keys")
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT row_hash, symbol, report_date FROM ibkr_raw_rows ORDER BY row_hash")).all()
        assert [(r[0], r[1], str(r[2]) if r[2] else None) for r in rows] == [
            ("h0", "BABA", "2026-10-27"), ("h1", "MSFT", "2026-10-26"), ("h2", None, None)]
        assert "ix_ibkr_raw_rows_snapshot" in {ix["name"] for ix in inspect(engine).get_indexes("ibkr_raw_rows")}
        _alembic(url, "downgrade", "0099_paper_trade_thesis_version")
        engine.dispose()
        engine = create_engine(url)
        columns = {c["name"] for c in inspect(engine).get_columns("ibkr_raw_rows")}
        assert "report_date" not in columns and "symbol" not in columns
        with engine.connect() as conn:
            assert conn.execute(text("SELECT COUNT(*) FROM ibkr_raw_rows")).scalar() == 3
    finally:
        engine.dispose()
