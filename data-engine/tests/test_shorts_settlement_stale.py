"""A recent fetch and trading day do not freshen old settlement data."""
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.services import short_positions_service as service


@pytest.mark.parametrize("age", [36, 365])
def test_old_settlement_is_stale_without_hiding_fresh_daily_data(monkeypatch, age):
    now = datetime.now(UTC)
    payload = {"source": "FINRA", "date": now.date().isoformat(),
               "short_interest": {"settlement_date": (now.date() - timedelta(days=age)).isoformat(),
                                  "short_interest": 20}}
    state = SimpleNamespace(metadata_=payload, last_success_at=now,
                            consecutive_errors=0, last_error=None)
    monkeypatch.setattr(service, "_state", lambda *_: state)
    result = service.read_shorts(None, SimpleNamespace(ticker="ABC"))
    assert result["status"] == "stale"
    assert result["data"] == payload
    assert "liquidación" in result["reason"] and "35 días" in result["reason"]


@pytest.mark.parametrize("age", [0, 15, 35])
def test_in_range_settlement_remains_available(monkeypatch, age):
    now = datetime.now(UTC)
    state = SimpleNamespace(metadata_={"source": "FINRA", "date": now.date().isoformat(),
                            "short_interest": {"settlement_date": (now.date() - timedelta(days=age)).isoformat()}},
                            last_success_at=now, consecutive_errors=0, last_error=None)
    monkeypatch.setattr(service, "_state", lambda *_: state)
    result = service.read_shorts(None, SimpleNamespace(ticker="ABC"))
    assert result["status"] == "available"
    assert result["reason"] is None
