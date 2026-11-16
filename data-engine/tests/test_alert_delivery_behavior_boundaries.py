"""Delivery-policy and news-source boundaries are fail-closed and local-only."""
from datetime import datetime
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base
from app.services import dca_alert_settings_service as policy
from app.services import tracked_news_alerts as news


def test_unscoped_policy_does_not_read_another_tenants_defaults():
    db = Mock(spec=Session)
    db.info = {}
    assert policy.stored_policy(db) is None
    assert policy.effective_policy(db) is None
    with pytest.raises(ValueError, match="Tenant identity"):
        policy.save_policy(db, 3, 1)
    db.scalar.assert_not_called()
    db.add.assert_not_called()
    db.commit.assert_not_called()


@pytest.mark.parametrize("up,down", [(True, 1), (3, False), (3.0, 1), (3, "1"), (-1, 1), (3, 5)])
def test_invalid_directional_policy_never_writes(up, down):
    db = Mock(spec=Session)
    db.info = {"tenant_id": 1}
    with pytest.raises(ValueError, match="0..4"):
        policy.save_policy(db, up, down)
    db.scalar.assert_not_called()
    db.add.assert_not_called()
    db.commit.assert_not_called()


@pytest.mark.parametrize("url", [None, "", 123, "https://[broken", "https://u:p@example.com/article", "file:///tmp/article"])
def test_news_without_safe_source_url_cannot_be_a_citation(url):
    assert news._valid_source_url(url) is None


def test_news_source_url_trim_keeps_original_article_path():
    assert news._valid_source_url(" https://example.com/article?a=1#section ") == "https://example.com/article?a=1#section"


def test_naive_time_rejected_before_scanning_news(monkeypatch):
    db = Mock(spec=Session)
    db.info = {"tenant_id": 1}
    monkeypatch.setattr(news, "generation_language", lambda _: "es")
    with pytest.raises(ValueError, match="Timezone-aware"):
        news.evaluate(db, now=datetime(2026, 11, 1, 12))
    db.scalars.assert_not_called()
    db.commit.assert_not_called()


def test_no_tracked_companies_produces_no_alert_or_dispatch(monkeypatch):
    from datetime import UTC
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    dispatch = Mock(side_effect=AssertionError("no tracked news may dispatch"))
    monkeypatch.setattr(news.NotificationService, "dispatch", dispatch)
    with Session(engine) as db:
        db.info["tenant_id"] = 1
        result = news.evaluate(db, now=datetime(2026, 11, 1, tzinfo=UTC))
        assert result == {"eligible_companies": 0, "examined": 0, "created": 0,
                          "duplicates": 0, "cooldown_skips": 0, "unverified_skips": 0}
    engine.dispose()
    dispatch.assert_not_called()
