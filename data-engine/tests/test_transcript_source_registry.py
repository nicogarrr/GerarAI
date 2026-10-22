import pytest

from app.services import transcript_source_registry as reg

UBER_PDF = (
    "https://s23.q4cdn.com/407969754/files/doc_events/2026/Aug/05/Uber-Q2-26-Earnings-Call-Transcript.pdf"
)
UBER_PREPARED = (
    "https://s23.q4cdn.com/407969754/files/doc_earnings/2026/q2/transcript/Uber-Q2-26-Prepared-Remarks.pdf"
)


def test_registered_assets_are_official_for_their_own_ticker():
    for e in reg.all_entries():
        for a in e.assets:
            assert reg.is_official_transcript_url(e.ticker, a.url)
            assert a.kind == "transcript"


def test_same_cdn_account_other_pdf_is_not_official():
    # mismo host y cuenta q4cdn: presentaciones, prepared remarks o notas no son transcripcion
    assert reg.is_official_transcript_url("UBER", UBER_PDF)
    assert not reg.is_official_transcript_url("UBER", UBER_PREPARED)
    assert not reg.is_official_transcript_url(
        "UBER",
        "https://s23.q4cdn.com/407969754/files/doc_events/2026/Aug/05/Uber-Q2-26-Earnings-Presentation.pdf",
    )
    assert not reg.is_official_transcript_url("UBER", UBER_PDF + "?x=1")
    assert not reg.is_official_transcript_url("UBER", UBER_PDF.replace("https", "http"))


def test_urls_do_not_cross_tickers():
    assert not reg.is_official_transcript_url("META", UBER_PDF)
    assert not reg.is_official_transcript_url("BN", UBER_PDF)


def test_unverified_tickers_never_official():
    for t in ("ASTS", "RKLB", "BABA", "ONDS", "KRKNF", "HYMC", "ZZZZ", "SDS"):
        assert not reg.is_official_transcript_url(t, UBER_PDF)
        assert not reg.get_entry(t) or not reg.get_entry(t).assets


def test_third_party_never_official():
    assert not reg.is_official_transcript_url(
        "UBER", "https://stockanalysis.com/stocks/uber/transcripts/661328-q2-2026/"
    )


def test_statuses_and_notes_are_honest():
    assert reg.get_entry("rklb").status == reg.WEBCAST_ONLY
    assert reg.get_entry("KRKNF").status == reg.NOT_LISTED_ON_IR_PAGE
    assert reg.get_entry("BABA").status == reg.PAGE_MENTIONS_TRANSCRIPT
    assert "No prueba" in reg.get_entry("HYMC").note
    assert reg.get_entry("SDS") is None


def test_invalid_entries_rejected():
    with pytest.raises(ValueError):
        reg.SourceEntry("X", "inventado", "https://x", "2026-10-22")
    with pytest.raises(ValueError):
        reg.SourceEntry("X", reg.OFFICIAL_TRANSCRIPT_PDF, "https://x", "2026-10-22")
    asset = reg.VerifiedAsset("https://x.example/a.pdf", "Transcript", "Q1 2026")
    with pytest.raises(ValueError):
        reg.SourceEntry("X", reg.WEBCAST_ONLY, "https://x", "2026-10-22", (asset,))
    with pytest.raises(ValueError):
        reg.VerifiedAsset("http://x.example/a.pdf", "Transcript", "Q1 2026")
    with pytest.raises(ValueError):
        reg.VerifiedAsset("https://x.example/a.pdf", "Presentation", "Q1 2026", kind="presentation")
