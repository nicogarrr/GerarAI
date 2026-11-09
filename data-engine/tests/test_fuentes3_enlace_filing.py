"""Enlace al filing exacto de cada cifra SEC (no al listado genérico de la empresa)."""
from __future__ import annotations

from types import SimpleNamespace

from app.core.source_urls import sec_filing_url

GENERIC = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&ticker=AAPL&type=10-K"
INDEX = "https://www.sec.gov/Archives/edgar/data/320193/000119312510012091/0001193125-10-012091-index.htm"


def test_generic_listing_becomes_filing_index() -> None:
    assert sec_filing_url(GENERIC, "0001193125-10-012091", "0000320193") == INDEX
    assert sec_filing_url(None, "000119312510012091", 320193) == INDEX


def test_keeps_url_without_accession_or_cik_or_when_already_specific() -> None:
    assert sec_filing_url(GENERIC, None, "0000320193") == GENERIC
    assert sec_filing_url(GENERIC, "0001193125-10-012091", None) == GENERIC
    assert sec_filing_url(GENERIC, "no-es-acceso", "320193") == GENERIC
    doc = "https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/aapl-20250927.htm"
    assert sec_filing_url(doc, "0000320193-25-000079", "320193") == doc
    assert sec_filing_url("https://filings.xbrl.org/api/filings (fxo_id=1)", None, None) is None


def test_own_consensus_citations_point_to_the_filing() -> None:
    from app.services import own_consensus

    fact = SimpleNamespace(period="2025-09-27:FY", value=7.46, filed=None, source_url=GENERIC,
                           accession_number="0001193125-10-012091")

    class _DB:
        def scalars(self, _stmt):  # noqa: ANN001, ANN202
            return SimpleNamespace(all=lambda: [fact])

    rows = own_consensus._facts(_DB(), SimpleNamespace(id=1, cik="0000320193"), "eps_diluted")  # noqa: SLF001
    assert rows == [("2025-09-27:FY", 7.46, None, INDEX)]
