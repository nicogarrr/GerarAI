"""Un subtotal conocido no es el importe completo de compras/ventas."""
from datetime import date

import pytest

from app.models.entities import InsiderTransaction
from app.services.insider_feed import build_feed
from tests.test_insider_feed import _persist
from tests.test_insider_monitor import _cleanup, _db


@pytest.mark.parametrize("code,prefix", [("P", "buy"), ("S", "sell")])
@pytest.mark.parametrize("missing", [False, True])
def test_totales_no_presentan_importe_desconocido_como_cero(code, prefix, missing):
    db = _db()
    try:
        _cleanup(db)
        _persist(db)
        tx = db.query(InsiderTransaction).one()
        tx.code = code
        tx.value = None if missing else 0.0
        db.commit()
        totals = build_feed(db, today=date(2024, 3, 20), days=3650)["totals"]
        assert totals[f"{prefix}_count"] == 1
        assert totals[f"{prefix}_value"] == (None if missing else 0.0)
        assert totals[f"{prefix}_known_value"] == 0.0
        assert totals[f"{prefix}_value_missing"] == int(missing)
    finally:
        db.rollback()
        _cleanup(db)
        db.close()


@pytest.mark.parametrize("code,prefix", [("P", "buy"), ("S", "sell")])
def test_totales_exponen_subtotal_sin_confundirlo_con_total(code, prefix):
    db = _db()
    try:
        _cleanup(db)
        _persist(db)
        tx = db.query(InsiderTransaction).one()
        tx.code, tx.value = code, 100.0
        db.add(InsiderTransaction(
            filing_id=tx.filing_id, tenant_id=None, accession_number=tx.accession_number,
            issuer_ticker=tx.issuer_ticker, insider=tx.insider, form=tx.form,
            code=code, shares=10, price=None, value=None, tx_date=tx.tx_date,
            is_derivative=False, fingerprint="test-feed-unknown",
        ))
        db.commit()
        totals = build_feed(db, today=date(2024, 3, 20), days=3650)["totals"]
        assert totals[f"{prefix}_count"] == 2
        assert totals[f"{prefix}_value"] is None
        assert totals[f"{prefix}_known_value"] == 100.0
        assert totals[f"{prefix}_value_missing"] == 1
    finally:
        db.rollback()
        _cleanup(db)
        db.close()
