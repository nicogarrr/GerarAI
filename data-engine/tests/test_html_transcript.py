"""Adaptador de transcripcion HTML del emisor. Contenido SINTETICO, sin red."""
import base64
import hashlib
from datetime import date

import pytest

from app.services.commitment_primary_pipeline import (
    PrimarySourceError,
    fetch_registered_document_isolated,
    html_visible_text,
)
from app.services.transcript_source_registry import get_entry

URL = get_entry("RXRX").assets[0].url
BODY = "<html><head><title>t</title><script>var x=1;</script></head><body><nav>menu</nav>" + (
    "<p>" + " ".join(f"palabra{i}" for i in range(260)) + "</p>") + "<footer>pie</footer></body></html>"


def _runner(content: bytes, final_url: str = URL, ctype: str = "text/html"):
    def run(argv, deadline):  # noqa: ARG001
        assert argv[-1] == "html"  # modo html del hijo acotado
        return {"html_b64": base64.b64encode(content).decode(), "final_url": final_url,
                "content_type": ctype, "bytes_sha256": hashlib.sha256(content).hexdigest(),
                "byte_size": len(content)}
    return run


def test_registry_marks_rxrx_as_html_search_origin():
    a = get_entry("RXRX").assets[0]
    assert a.format == "html" and a.origin == "url_dominio_oficial_por_busqueda"
    assert a.call_date == "2026-08-05"


def test_visible_text_skips_script_nav_footer():
    txt = html_visible_text(BODY.encode())
    assert "palabra0" in txt and "var x" not in txt and "menu" not in txt and "pie" not in txt


def test_html_transcript_fetched_via_isolated_runner():
    from app.services import commitment_primary_pipeline as pp
    pp._CACHE.clear()
    doc, meta = fetch_registered_document_isolated(
        "RXRX", URL, today=date(2026, 10, 22), runner=_runner(BODY.encode()))
    assert doc.extractor == "html-stdlib" and len(doc.text.split()) >= 260
    assert doc.bytes_sha256 == hashlib.sha256(BODY.encode()).hexdigest() and not meta["cache_hit"]


def test_html_transcript_rejects_wrong_url_type_and_thin_text():
    from app.services import commitment_primary_pipeline as pp
    pp._CACHE.clear()
    with pytest.raises(PrimarySourceError):
        fetch_registered_document_isolated(
            "RXRX", URL, today=date(2026, 10, 22),
            runner=_runner(BODY.encode(), final_url="https://evil.invalid/x"))
    pp._CACHE.clear()
    with pytest.raises(PrimarySourceError):
        fetch_registered_document_isolated(
            "RXRX", URL, today=date(2026, 10, 22),
            runner=_runner(b"<html><body><p>poco</p></body></html>"))
    with pytest.raises(PrimarySourceError):
        fetch_registered_document_isolated(
            "RXRX", URL + "x", today=date(2026, 10, 22), runner=_runner(BODY.encode()))
