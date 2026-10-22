import pytest

from app.services import transcript_source_registry as reg


def test_examples_are_official_for_their_own_ticker():
    for e in reg.all_entries():
        if e.status == reg.OFFICIAL_TRANSCRIPT_PDF:
            assert reg.is_official_transcript_url(e.ticker, e.example_pdf)


def test_shared_cdn_prefix_does_not_cross_tickers():
    uber = reg.get_entry("UBER").example_pdf
    assert not reg.is_official_transcript_url("META", uber)
    assert not reg.is_official_transcript_url("BN", uber)
    assert not reg.is_official_transcript_url("UBER", "https://s23.q4cdn.com/999999999/files/x.pdf")


def test_non_official_or_unverified_never_official():
    assert not reg.is_official_transcript_url("UBER", "http://s23.q4cdn.com/407969754/files/x.pdf")
    assert not reg.is_official_transcript_url("UBER", "https://stockanalysis.com/stocks/uber/transcripts/1/")
    for t in ("ASTS", "RKLB", "BABA", "ONDS", "KRKNF", "HYMC", "ZZZZ"):
        assert not reg.is_official_transcript_url(t, "https://s23.q4cdn.com/407969754/files/x.pdf")


def test_webcast_only_is_not_transcript_and_lookup_is_case_insensitive():
    assert reg.get_entry("rklb").status == reg.WEBCAST_ONLY
    assert reg.get_entry("SDS") is None


def test_invalid_entry_rejected():
    with pytest.raises(ValueError):
        reg.SourceEntry("X", "inventado", "https://x", "2026-10-22")
    with pytest.raises(ValueError):
        reg.SourceEntry("X", reg.OFFICIAL_TRANSCRIPT_PDF, "https://x", "2026-10-22")


def test_link_verified_only_where_href_was_read():
    verified = {e.ticker for e in reg.all_entries() if e.link_verified_on_ir_page}
    assert verified == {"META", "BN", "UBER"}
    for e in reg.all_entries():
        if e.link_verified_on_ir_page:
            assert e.status == reg.OFFICIAL_TRANSCRIPT_PDF


def test_absence_statuses_are_not_claims_of_non_existence():
    assert reg.get_entry("KRKNF").status == reg.NOT_LISTED_ON_IR_PAGE
    assert reg.get_entry("ONDS").status == reg.WEBCAST_ONLY
    assert "No prueba" in reg.get_entry("HYMC").note
