"""Missing recipient identity never becomes consent or an invented email target.
Pure local read tests: no email or other external action is performed.
"""
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy.orm import Session

from app.models import ResearchAlert
from app.services import email_alerts, outbound_alerts


@pytest.mark.parametrize("category,user", [(None, "u"), ("earnings", None)])
def test_unknown_category_or_missing_user_cannot_resolve_destination(monkeypatch, category, user):
    db = Mock(spec=Session)
    db.info = {"user_id": user}
    alert = ResearchAlert(tenant_id=1)
    monkeypatch.setattr(outbound_alerts, "alert_category", lambda *_: category)
    assert email_alerts.preference_for(db, alert) is None
    assert email_alerts.opted_out(db, alert) is False
    db.scalar.assert_not_called()


def test_enabled_preference_without_signed_binding_is_not_a_target(monkeypatch):
    now = datetime(2026, 11, 1, tzinfo=UTC)
    db = Mock(spec=Session)
    db.info = {"user_id": "u"}
    preference = SimpleNamespace(enabled=True, enabled_at=now)
    db.scalar.side_effect = [preference, None]
    alert = ResearchAlert(tenant_id=1, created_at=now)
    monkeypatch.setattr(outbound_alerts, "alert_category", lambda *_: "earnings")
    monkeypatch.setattr(outbound_alerts, "alert_after_opt_in", lambda *_: True)
    assert email_alerts.preference_for(db, alert) is None
    assert db.scalar.call_count == 2
