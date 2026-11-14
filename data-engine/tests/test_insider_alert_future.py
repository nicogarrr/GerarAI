"""A future transaction is not a recent completed purchase."""
from datetime import date

import pytest

from app.models.entities import InsiderTransaction
from app.services import insider_alerts
from tests.test_insider_alerts import _cleanup, _db, _seed_big_buy


@pytest.mark.parametrize('age_limit', [30, None])
def test_future_purchase_is_not_an_alert_candidate(monkeypatch, age_limit):
    monkeypatch.setattr(insider_alerts, 'ALERT_MAX_AGE_DAYS', age_limit)
    db = _db()
    try:
        _cleanup(db)
        _seed_big_buy(db)
        tx = db.query(InsiderTransaction).one()
        tx.tx_date = '2026-11-15'
        db.commit()
        assert insider_alerts._candidate_purchases(db, None, date(2026, 11, 14)) == []
        result = insider_alerts.evaluate(db, today=date(2026, 11, 14))
        assert result['candidates'] == 0
        assert result['alerts_created'] == 0
        assert result['errors'] == []
    finally:
        db.rollback()
        _cleanup(db)
        db.close()
