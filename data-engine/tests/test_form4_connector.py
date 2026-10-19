"""F310: EDGAR apunta primaryDocument a la versión renderizada (HTML XSLT);
el conector debe reescribir al documento crudo y reintentar con fallback."""

from __future__ import annotations

import pytest

from app.services.connectors.form4 import fetch_filing_xml, raw_document_url

RENDERED = "https://www.sec.gov/Archives/edgar/data/320193/000114036126037584/xslF345X06/form4.xml"
RAW = "https://www.sec.gov/Archives/edgar/data/320193/000114036126037584/form4.xml"
XML_BODY = '<?xml version="1.0"?>\n<ownershipDocument><documentType>4</documentType></ownershipDocument>'
HTML_BODY = '<!DOCTYPE html PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN">\n<html><head><title>SEC FORM 4</title>'


class _FakeResponse:
    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self) -> None:
        return None


class _FakeClient:
    """Client httpx simulado: registra las URL pedidas y sirve por mapa."""

    def __init__(self, bodies: dict[str, str]):
        self.bodies = bodies
        self.requested: list[str] = []

    def get(self, url: str, headers: dict | None = None) -> _FakeResponse:
        self.requested.append(url)
        if url not in self.bodies:
            raise AssertionError(f"unexpected URL: {url}")
        return _FakeResponse(self.bodies[url])


def test_raw_document_url_strips_rendered_xsl_segment():
    assert raw_document_url(RENDERED) == RAW


def test_raw_document_url_leaves_plain_urls_untouched():
    plain = "https://www.sec.gov/Archives/edgar/data/320193/000114036126037584/form4.xml"
    assert raw_document_url(plain) == plain


def test_fetch_returns_xml_served_directly():
    client = _FakeClient({RAW: XML_BODY})
    assert fetch_filing_xml(RAW, client=client) == XML_BODY
    assert client.requested == [RAW]


def test_fetch_falls_back_to_raw_document_when_served_rendered_html():
    client = _FakeClient({RENDERED: HTML_BODY, RAW: XML_BODY})
    assert fetch_filing_xml(RENDERED, client=client) == XML_BODY
    assert client.requested == [RENDERED, RAW]


def test_fetch_raises_when_raw_variant_is_also_html():
    client = _FakeClient({RENDERED: HTML_BODY, RAW: HTML_BODY})
    with pytest.raises(ValueError, match="not XML"):
        fetch_filing_xml(RENDERED, client=client)


def test_fetch_raises_when_html_has_no_raw_variant():
    plain = "https://www.sec.gov/Archives/edgar/data/320193/000114036126037584/form4.xml"
    client = _FakeClient({plain: HTML_BODY})
    with pytest.raises(ValueError, match="no raw variant"):
        fetch_filing_xml(plain, client=client)


def test_fetch_still_rejects_non_sec_hosts():
    with pytest.raises(ValueError, match="sec.gov"):
        fetch_filing_xml("https://example.com/xslF345X06/form4.xml", client=_FakeClient({}))


def test_derivative_rows_keep_security_title_so_equal_grants_are_distinguishable():
    from app.services.connectors.form4 import parse_form4_xml
    from app.services.insider_persistence import _data_quality

    def row(title: str, shares: str) -> str:
        return (
            "<derivativeTransaction>"
            f"<securityTitle><value>{title}</value></securityTitle>"
            "<transactionDate><value>2026-05-30</value></transactionDate>"
            "<transactionCoding><transactionCode>A</transactionCode></transactionCoding>"
            f"<transactionAmounts><transactionShares><value>{shares}</value></transactionShares>"
            "<transactionPricePerShare><value>0</value></transactionPricePerShare>"
            "<transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>"
            "</transactionAmounts></derivativeTransaction>"
        )

    xml = (
        "<ownershipDocument><issuer><issuerCik>0000050863</issuerCik><issuerName>INTEL</issuerName>"
        "<issuerTradingSymbol>INTC</issuerTradingSymbol></issuer>"
        "<reportingOwner><reportingOwnerId><rptOwnerCik>1</rptOwnerCik><rptOwnerName>Katouzian Aliyar</rptOwnerName>"
        "</reportingOwnerId></reportingOwner>"
        f"<derivativeTable>{row('Restricted Stock Units', '32729')}{row('Performance Stock Units', '32729')}</derivativeTable>"
        "</ownershipDocument>"
    )
    txs = parse_form4_xml(xml)["transactions"]
    assert [t["security_title"] for t in txs] == ["Restricted Stock Units", "Performance Stock Units"]
    assert _data_quality(txs[1])["security_title"] == "Performance Stock Units"
