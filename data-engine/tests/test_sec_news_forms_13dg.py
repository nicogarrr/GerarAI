"""La ingesta SEC del feed de noticias incluye SC 13D/13G (titulares >5%)
junto a los formularios periodicos; un caller puede seguir fijando forms."""

from __future__ import annotations

import asyncio

from app.services.connectors.base import ConnectorResult
from app.services.feed_ingestion_service import DEFAULT_SEC_NEWS_FORMS, FeedIngestionService


def test_default_sec_news_forms_cover_13d_13g_both_families():
    for form in (
        "SC 13D",
        "SC 13D/A",
        "SC 13G",
        "SC 13G/A",
        "SCHEDULE 13D",
        "SCHEDULE 13D/A",
        "SCHEDULE 13G",
        "SCHEDULE 13G/A",
    ):
        assert form in DEFAULT_SEC_NEWS_FORMS
    # Los periodicos/corrientes de antes siguen dentro.
    for form in ("10-K", "10-Q", "8-K", "20-F", "6-K"):
        assert form in DEFAULT_SEC_NEWS_FORMS


def test_poll_sec_defaults_to_news_forms_including_13dg(monkeypatch):
    captured: dict = {}

    async def fake_recent_filings(self, cik, *, forms=None, limit=40, ticker=None):
        captured["forms"] = forms
        return ConnectorResult(source="sec", items=[])

    monkeypatch.setattr(
        "app.services.connectors.sec.SECClient.recent_filings", fake_recent_filings
    )
    service = FeedIngestionService()
    asyncio.run(service.poll_sec("1780312", ticker="ASTS"))
    assert captured["forms"] == DEFAULT_SEC_NEWS_FORMS


def test_poll_sec_respects_explicit_forms(monkeypatch):
    captured: dict = {}

    async def fake_recent_filings(self, cik, *, forms=None, limit=40, ticker=None):
        captured["forms"] = forms
        return ConnectorResult(source="sec", items=[])

    monkeypatch.setattr(
        "app.services.connectors.sec.SECClient.recent_filings", fake_recent_filings
    )
    service = FeedIngestionService()
    asyncio.run(service.poll_sec("1780312", ticker="ASTS", forms={"10-K"}))
    assert captured["forms"] == {"10-K"}
