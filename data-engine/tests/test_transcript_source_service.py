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
