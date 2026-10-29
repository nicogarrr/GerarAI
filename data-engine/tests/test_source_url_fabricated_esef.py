"""Enlaces ESEF fabricados antes de #2968: se neutralizan al leer, sin migracion."""
from app.models import Document, FinancialFact

FAKE = "https://filings.xbrl.org/api/filings (fxo_id=12345)"
REAL = "https://www.sec.gov/Archives/edgar/data/789019/000095017025087843/msft-20250630.htm"


def _fact(url: str | None) -> FinancialFact:
    fact = FinancialFact(metric="revenue", value=1, unit="EUR", period="2025-12-31:FY")
    fact.source = Document(title="ESEF XBRL facts - ITX", source_type="ESEF", source_url=url)
    return fact


def test_stale_fabricated_esef_link_is_not_exposed_on_facts():
    assert _fact(FAKE).source_url is None


def test_real_and_missing_urls_are_unchanged():
    assert _fact(REAL).source_url == REAL
    assert _fact(None).source_url is None
    assert FinancialFact(metric="m", value=1).source_url is None


def test_sources_listing_and_chat_use_the_same_rule():
    from app.core.source_urls import linkable_source_url

    assert linkable_source_url(FAKE) is None
    assert linkable_source_url(REAL) == REAL
    assert linkable_source_url(None) is None
