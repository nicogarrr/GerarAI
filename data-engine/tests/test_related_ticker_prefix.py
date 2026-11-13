"""An unknown qualified symbol never proves its bare prefix company."""
import pytest

from app.services.news_related_tickers import CompanyRef, build_index, mentioned_companies


@pytest.mark.parametrize("text", ["Watch $AAA-B", "Watch $AAA.ABCD", "NASDAQ: AAA-B", "NASDAQ: AAA.ABCD"])
def test_unknown_full_symbol_does_not_link_prefix(text):
    names, tickers = build_index([CompanyRef(1, "AAA", "Example Industries", "USD")])
    assert mentioned_companies(text, names, tickers) == []


@pytest.mark.parametrize("text", ["Watch $AAA.", "NASDAQ: AAA.", "($AAA)", "NASDAQ: AAA, next"])
def test_plain_symbol_with_punctuation_still_links(text):
    names, tickers = build_index([CompanyRef(1, "AAA", "Example Industries", "USD")])
    assert [c.id for c in mentioned_companies(text, names, tickers)] == [1]


def test_known_dotted_symbol_links_the_full_company_not_the_prefix():
    names, tickers = build_index([CompanyRef(1, "AAA", "Example Industries", "USD"),
                                CompanyRef(2, "AAA.L", "Another Business", "GBP")])
    assert [c.id for c in mentioned_companies("Watch $AAA.L", names, tickers)] == [2]
