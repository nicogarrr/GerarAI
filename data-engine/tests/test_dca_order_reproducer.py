"""Bounded reproduction of foreign rows left before the DCA API fixture."""
import pytest
from sqlalchemy import delete, select

from app.core.database import SessionLocal, init_db
from app.models import WatchItem

FOREIGN=[f'AAAORDER{i:02}' for i in range(10)]

@pytest.fixture
def client(monkeypatch):
    from tests.test_dca_signals_api import client as base_client
    init_db()
    with SessionLocal() as db:
        db.add_all([WatchItem(symbol=s) for s in FOREIGN]);db.commit()
    try:
        yield from base_client.__wrapped__(monkeypatch)
    finally:
        with SessionLocal() as db:
            db.execute(delete(WatchItem).where(WatchItem.symbol.in_(FOREIGN)));db.commit()


def test_manual_evaluates_requested_fixture_symbol_with_foreign_rows(client):
    from tests.test_dca_run_log import test_manual_run_is_recorded_and_symbol_is_evaluated
    test_manual_run_is_recorded_and_symbol_is_evaluated(client)
    # Isolation must not delete rows belonging to another fixture or create
    # evaluation state for them merely to make this test pass.
    from app.models import DcaSignalState
    with SessionLocal() as db:
        assert set(db.scalars(select(WatchItem.symbol).where(WatchItem.symbol.in_(FOREIGN)))) == set(FOREIGN)
        assert not db.scalars(select(DcaSignalState).where(DcaSignalState.symbol.in_(FOREIGN))).all()

