"""A purchase is not observable before its filing publication date."""
from datetime import date

import pytest

from app.models.entities import InsiderFiling, InsiderTransaction
from app.services import insider_alerts
from tests.test_insider_alerts import _cleanup, _db, _seed_big_buy


@pytest.mark.parametrize('age_limit', [30, None])
@pytest.mark.parametrize('published,visible', [
    ('2026-11-15', False), ('2026-11-14', True), ('2026-11-13', True),
    (None, True), ('unreadable', True),
])
def test_filing_publication_independently_bounds_alert_candidates(monkeypatch, age_limit, published, visible):
    monkeypatch.setattr(insider_alerts, 'ALERT_MAX_AGE_DAYS', age_limit)
    db = _db()
    try:
        _cleanup(db)
        _seed_big_buy(db)
        db.query(InsiderTransaction).one().tx_date = '2026-11-13'
        db.query(InsiderFiling).one().filing_date = published
        db.commit()
        rows = insider_alerts._candidate_purchases(db, None, date(2026, 11, 14))
        assert len(rows) == int(visible)
        if not visible:
            result = insider_alerts.evaluate(db, today=date(2026, 11, 14))
            assert result['candidates'] == 0
            assert result['alerts_created'] == 0
            assert result['errors'] == []
    finally:
        db.rollback()
        _cleanup(db)
        db.close()
