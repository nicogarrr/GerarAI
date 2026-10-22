import pytest

from app.services import transcript_source_service as svc


def test_rejects_http_and_unlisted_hosts():
    for url in ("http://s21.q4cdn.com/x.pdf", "https://evil.example/x.pdf", "https://s21.q4cdn.com.evil.example/x.pdf"):
        with pytest.raises(svc.TranscriptSourceError):
            svc.fetch_transcript_text(url)


def test_env_extends_allowlist(monkeypatch):
    monkeypatch.setenv("COMMITMENT_TRANSCRIPT_HOSTS", "ir.example.invalid")
    assert svc.is_allowed_source("https://ir.example.invalid/a.pdf")
    assert not svc.is_allowed_source("http://ir.example.invalid/a.pdf")


def test_rejects_non_pdf(monkeypatch):
    monkeypatch.setattr(svc, "fetch_public_url", lambda *a, **k: (b"<html>hi</html>", "text/html", "u"))
    with pytest.raises(svc.TranscriptSourceError, match="PDF"):
        svc.fetch_transcript_text("https://s21.q4cdn.com/x")


def test_download_error_is_bounded(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("secret internal detail 10.0.0.1")

    monkeypatch.setattr(svc, "fetch_public_url", boom)
    with pytest.raises(svc.TranscriptSourceError) as err:
        svc.fetch_transcript_text("https://s21.q4cdn.com/x")
    assert "10.0.0.1" not in str(err.value)


def test_extracts_text_from_synthetic_pdf(monkeypatch):
    from io import BytesIO

    from pypdf import PdfWriter

    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    buf = BytesIO()
    w.write(buf)
    monkeypatch.setattr(svc, "fetch_public_url", lambda *a, **k: (buf.getvalue(), "application/pdf", "u"))
    with pytest.raises(svc.TranscriptSourceError, match="insuficiente"):
        svc.fetch_transcript_text("https://s21.q4cdn.com/x")


def test_check_source_matches_mismatches_and_unreadable():
    from datetime import date

    head = "Acme Corp (ACME)\nSecond Quarter 2030 Results Conference Call\nJuly 1st, 2030\n"
    assert svc.check_source(head, ticker="acme", call_date=date(2030, 7, 1)) == "header_matches"
    with pytest.raises(svc.TranscriptSourceError, match="ACME"):
        svc.check_source(head, ticker="OTHR", call_date=date(2030, 7, 1))
    with pytest.raises(svc.TranscriptSourceError, match="2030-07-01"):
        svc.check_source(head, ticker="ACME", call_date=date(2030, 8, 1))
    assert svc.check_source("sin cabecera legible", ticker="ACME", call_date=date(2030, 7, 1)) == "header_unreadable"


def test_throttle_blocks_rapid_repeat():
    assert svc.throttle(987654) is True
    assert svc.throttle(987654) is False


def test_timezone_in_parentheses_is_not_a_ticker():
    from datetime import date

    head = "BROOKFIELD CORPORATION\nTRANSCRIPT: Q2 2026 CONFERENCE CALL\nAUGUST 13, 2026, at 10:00 a.m. (ET)\n"
    assert svc.observe_header(head) == {"ticker": None, "call_date": date(2026, 8, 13)}
    assert svc.check_source(head, ticker="BN", call_date=date(2026, 8, 13)) == "header_unreadable"
