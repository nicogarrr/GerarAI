from datetime import UTC, datetime

from app.services.thesis_evidence_service import _filing_published_at


def test_filing_date_becomes_utc_datetime():
    assert _filing_published_at("2026-10-14") == datetime(2026, 10, 14, tzinfo=UTC)


def test_invalid_or_missing_is_none():
    assert _filing_published_at(None) is None
    assert _filing_published_at("") is None
    assert _filing_published_at("nope") is None
