"""Relevancia conservadora: solo baja materialidad, nunca descarta."""

from types import SimpleNamespace

from app.services.materiality_service import (
    UNRELATED_NEWS_MAX_MATERIALITY,
    is_unrelated_generic_news,
    mentions_company,
)

AAPL = SimpleNamespace(ticker="AAPL", name="Apple Inc.")


def test_mentions_ticker_or_name():
    assert mentions_company("Apple unveils new iPhone", AAPL)
    assert mentions_company("AAPL shares rise", AAPL)
    assert not mentions_company("CoreWeave signs new cloud contract", AAPL)
    assert not mentions_company("Robinhood KPI for September", AAPL)


def test_generic_source_unrelated_is_flagged():
    assert is_unrelated_generic_news("CoreWeave signs cloud deal", AAPL, "news", "https://x.com/a")
    assert UNRELATED_NEWS_MAX_MATERIALITY < 7


def test_filing_or_related_never_flagged():
    assert not is_unrelated_generic_news("Apple unveils iPhone", AAPL, "news", "https://x.com/a")
    assert not is_unrelated_generic_news(
        "Current report", AAPL, "sec_filing", "https://www.sec.gov/Archives/x"
    )
    assert not is_unrelated_generic_news("Whatever", None, "news", None)
