"""Pipeline de evidencia primaria sin red: fetcher y extractor inyectados, SINTETICO."""
import hashlib
from datetime import date
from decimal import Decimal

import pytest

from app.services.commitment_primary_pipeline import (
    PrimarySourceError,
    fetch_registered_document,
    quote_for_fact,
)
from app.services.followup_primary_evidence_adapter import ReportedObservation

URL = (
    "https://s23.q4cdn.com/407969754/files/doc_events/2026/Aug/05/"
    "Uber-Q2-26-Earnings-Call-Transcript.pdf"
)
TODAY = date(2026, 10, 22)
PAGES = [
    "Uber Technologies (UBER) Q2 2026 Earnings Call 05-Aug-2026 " + "filler " * 120,
    "intro " * 100,
    "Q2 was another outstanding quarter. Gross bookings grew 22% year-on-year to more than $58 billion. " + "x " * 100,
]
BYTES = b"%PDF-1.7 synthetic"


def _fetcher(content=BYTES, final=URL, calls=None):
    def fetch(url, **kw):
        if calls is not None:
            calls.append((url, kw["allowed_url"]))
        return content, "application/pdf", final
    return fetch


def _doc(**kw):
    return fetch_registered_document(
        "UBER", URL, today=TODAY, fetcher=_fetcher(**kw), page_extractor=lambda b: PAGES
    )


def test_document_records_byte_and_text_hashes_and_pages():
    doc = _doc()
    assert doc.bytes_sha256 == hashlib.sha256(BYTES).hexdigest()
    assert doc.text_sha256 == hashlib.sha256(doc.text.encode()).hexdigest()
    assert doc.text.count("\f") == 2 and doc.extractor.startswith("pypdf==")
    assert doc.asset.published_on == date(2026, 8, 5)


def test_fetch_policy_is_exact_url_equality_not_host():
    calls = []
    _doc(calls=calls)
    _, allowed = calls[0]
    assert allowed(URL)
    assert not allowed(URL.replace("Transcript", "Presentation"))


@pytest.mark.parametrize(
    "ticker,url",
    [
        ("UBER", URL.replace("Transcript", "Presentation")),  # mismo host/CDN, no registrado
        ("UBER", "http://s23.q4cdn.com/407969754/x.pdf"),
        ("RKLB", URL),  # activo de otro ticker
        ("ASTS", URL),
    ],
)
def test_unregistered_url_is_rejected_before_any_fetch(ticker, url):
    def boom(*a, **k):
        raise AssertionError("no debe descargar")

    with pytest.raises(PrimarySourceError):
        fetch_registered_document(ticker, url, today=TODAY, fetcher=boom)


def test_redirect_to_other_url_and_non_pdf_are_rejected():
    with pytest.raises(PrimarySourceError):
        _doc(final="https://evil.example/x.pdf")
    with pytest.raises(PrimarySourceError):
        _doc(content=b"<html>")


def test_quote_comes_from_adapter_with_page_three_and_span():
    doc = _doc()
    fact = ReportedObservation(
        1, 1, 7, "gross_bookings_growth_yoy", Decimal("22"), "%", URL,
        doc.asset.period, True, False,
    )
    out = quote_for_fact(tenant_id=1, company_id=1, document=doc, fact=fact, today=TODAY)
    ev = out.result.evidence
    assert out.result.reason_code == "literal_reported_result"
    assert ev.page == 3 and ev.text_sha256 == doc.text_sha256
    assert doc.text[ev.char_start:ev.char_end] == ev.quote


def test_wrong_value_gives_no_evidence():
    doc = _doc()
    fact = ReportedObservation(
        1, 1, 7, "gross_bookings_growth_yoy", Decimal("25"), "%", URL,
        doc.asset.period, True, False,
    )
    out = quote_for_fact(tenant_id=1, company_id=1, document=doc, fact=fact, today=TODAY)
    assert out.result.evidence is None


def test_wrong_content_type_is_rejected():
    def fetch(url, **kw):
        return BYTES, "text/html", URL

    with pytest.raises(PrimarySourceError):
        fetch_registered_document("UBER", URL, today=TODAY, fetcher=fetch,
                                  page_extractor=lambda b: PAGES)
