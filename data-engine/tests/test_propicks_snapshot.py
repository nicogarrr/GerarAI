from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select

from app.models import MarketPrice
from app.models.propick_snapshot import PropickSnapshot
from app.services.propicks_snapshot_service import freeze_monthly_snapshot
from tests.test_propicks_funnel import _company, _db, _five_good_years, _full_metrics


def test_empty_month_is_not_frozen():
    with _db() as db:
        assert freeze_monthly_snapshot(db) is None
        assert db.scalars(select(PropickSnapshot)).all() == []


def test_snapshot_is_point_in_time_and_immutable_per_month():
    with _db() as db:
        c = _company("SNAP")
        db.add(c)
        db.flush()
        _full_metrics(db, c)
        _five_good_years(db, c)
        db.add(MarketPrice(company_id=c.id, date=date(2026, 10, 16), close=Decimal("12.5"), volume=10))
        db.commit()
        first = freeze_monthly_snapshot(db, now=datetime(2026, 10, 19, tzinfo=UTC))
        assert first is not None and first.month == "2026-10"
        pick = first.payload["picks"][0]
        assert pick["ticker"] == "SNAP" and pick["price"] == 12.5 and pick["price_date"] == "2026-10-16"
        # second call in the same month returns the first one, unchanged
        again = freeze_monthly_snapshot(db, now=datetime(2026, 10, 30, tzinfo=UTC))
        assert again.id == first.id and again.as_of == first.as_of
        # a new month creates a new row
        nov = freeze_monthly_snapshot(db, now=datetime(2026, 11, 1, tzinfo=UTC))
        assert nov.id != first.id and nov.month == "2026-11"
