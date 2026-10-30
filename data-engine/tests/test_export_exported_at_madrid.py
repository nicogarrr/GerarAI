"""Export: `exported_at` es la fecha de Madrid, no el dia UTC del servidor."""

from datetime import UTC, datetime

import pytest

from app.core import local_date
from tests.test_export_position_currency import _export


@pytest.mark.parametrize(
    ("utc_now", "madrid_day"),
    [
        # 23:30 UTC del 30-oct (CET, +1) ya es el 31 en Madrid.
        (datetime(2026, 10, 30, 23, 30, tzinfo=UTC), "2026-10-31"),
        # 22:30 UTC del 30-jun (CEST, +2) ya es el 1-jul en Madrid.
        (datetime(2026, 6, 30, 22, 30, tzinfo=UTC), "2026-07-01"),
    ],
)
def test_exported_at_uses_madrid_date(monkeypatch, utc_now, madrid_day):
    monkeypatch.setattr(local_date, "_utc_now", lambda: utc_now)
    payload = _export(monkeypatch, lambda seed, portfolio: None, fmt="json").json()
    assert payload["exported_at"] == madrid_day
