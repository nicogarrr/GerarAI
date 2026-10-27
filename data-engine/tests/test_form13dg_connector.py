"""Conector SC 13D/13G: listado por CIK, documento crudo vs renderizado y
parse de portada (XML nuevo y SGML heredado). Regla madre: lo no parseable
queda en None (N/D); NUNCA se inventa una cifra."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.connectors.form13dg import (
    fetch_filing_document,
    parse_schedule13dg,
    raw_document_url,
    recent_form13dg_filings,
)

FIXTURES = Path(__file__).parent / "fixtures"
# Filing real: SC 13G de BlackRock sobre AST SpaceMobile, presentado
# 27-oct-2026 (accession 0002012383-26-003748), snapshot 30-sep-2026.
REAL_13G_XML = (FIXTURES / "schedule13g_asts_blackrock.xml").read_text(encoding="utf-8")

RENDERED = "https://www.sec.gov/Archives/edgar/data/1780312/000201238326003748/xslSCHEDULE_13G_X02/primary_doc.xml"
RAW = "https://www.sec.gov/Archives/edgar/data/1780312/000201238326003748/primary_doc.xml"
HTML_BODY = '<!DOCTYPE html PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN">\n<html><head><title>SEC</title>'


class _FakeResponse:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self) -> None:
        return None

    def json(self):
        import json

        return json.loads(self.text)


class _FakeClient:
    """Cliente httpx simulado: registra las URL pedidas y sirve por mapa."""

    def __init__(self, bodies: dict[str, str]):
        self.bodies = bodies
        self.requested: list[str] = []

    def get(self, url: str, headers: dict | None = None) -> _FakeResponse:
        self.requested.append(url)
        if url not in self.bodies:
            raise AssertionError(f"unexpected URL: {url}")
        return _FakeResponse(self.bodies[url])


# ---------------- Parse del XML real ----------------


def test_parse_real_13g_blackrock_all_fields():
    parsed = parse_schedule13dg(REAL_13G_XML)
    assert parsed["parsed_ok"] is True
    assert parsed["format"] == "xml"
    assert parsed["form"] == "SCHEDULE 13G"
    assert parsed["is_amendment"] is False
    assert parsed["holder_name"] == "BlackRock, Inc."
    assert parsed["aggregate_shares"] == 16115870
    assert parsed["percent_of_class"] == 5.4
    assert parsed["sole_voting_power"] == 14919314
    assert parsed["shared_voting_power"] == 0
    assert parsed["sole_dispositive_power"] == 16115870
    assert parsed["shared_dispositive_power"] == 0
    assert parsed["snapshot_date"] == "2026-09-30"
    assert parsed["signature_date"] == "2026-10-27"
    assert parsed["cusip"] == "00217D100"
    assert parsed["issuer_cik"] == "1780312"
    assert parsed["issuer_name"] == "AST SpaceMobile, Inc."
    assert parsed["filer_cik"] == "2012383"
    assert parsed["securities_class_title"] == "Class A Stock"
    assert parsed["rule"] == "Rule 13d-1(b)"
    assert len(parsed["holders"]) == 1
    assert parsed["holders"][0]["aggregate_shares"] == 16115870


AMENDMENT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/schedule13d">
<headerData><submissionType>SCHEDULE 13D/A</submissionType>
<filerInfo><filer><filerCredentials><cik>0001111111</cik></filerCredentials></filer></filerInfo>
</headerData>
<formData>
<coverPageHeader>
<securitiesClassTitle>Class A Stock</securitiesClassTitle>
<eventDateRequiresFilingThisStatement>06/15/2026</eventDateRequiresFilingThisStatement>
<issuerInfo><issuerCik>0001780312</issuerCik><issuerName>AST SpaceMobile, Inc.</issuerName>
<issuerCusips><issuerCusipNumber>00217D100</issuerCusipNumber></issuerCusips></issuerInfo>
</coverPageHeader>
<coverPageHeaderReportingPersonDetails>
<reportingPersonName>Activist Fund LP</reportingPersonName>
<reportingPersonBeneficiallyOwnedNumberOfShares>
<soleVotingPower>8000000</soleVotingPower><sharedVotingPower>0</sharedVotingPower>
<soleDispositivePower>8000000</soleDispositivePower><sharedDispositivePower>0</sharedDispositivePower>
</reportingPersonBeneficiallyOwnedNumberOfShares>
<reportingPersonBeneficiallyOwnedAggregateNumberOfShares>8,000,000</reportingPersonBeneficiallyOwnedAggregateNumberOfShares>
<classPercent>7.2</classPercent>
</coverPageHeaderReportingPersonDetails>
</formData>
</edgarSubmission>"""


def test_parse_amendment_13da_is_amendment_and_commas():
    parsed = parse_schedule13dg(AMENDMENT_XML)
    assert parsed["parsed_ok"] is True
    assert parsed["form"] == "SCHEDULE 13D/A"
    assert parsed["is_amendment"] is True
    assert parsed["holder_name"] == "Activist Fund LP"
    assert parsed["aggregate_shares"] == 8000000
    assert parsed["percent_of_class"] == 7.2
    assert parsed["snapshot_date"] == "2026-06-15"


def test_parse_xml_missing_fields_stay_none():
    xml = AMENDMENT_XML.replace("<classPercent>7.2</classPercent>", "").replace(
        "<reportingPersonBeneficiallyOwnedAggregateNumberOfShares>8,000,000</reportingPersonBeneficiallyOwnedAggregateNumberOfShares>",
        "",
    )
    parsed = parse_schedule13dg(xml)
    assert parsed["parsed_ok"] is True
    assert parsed["aggregate_shares"] is None
    assert parsed["percent_of_class"] is None
    # El resto sigue leyendose; solo falta lo que falta en el filing.
    assert parsed["holder_name"] == "Activist Fund LP"


def test_parse_percent_out_of_range_is_none():
    xml = AMENDMENT_XML.replace("<classPercent>7.2</classPercent>", "<classPercent>154.0</classPercent>")
    parsed = parse_schedule13dg(xml)
    assert parsed["percent_of_class"] is None


def test_parse_broken_xml_never_invents():
    parsed = parse_schedule13dg('<?xml version="1.0"?><edgarSubmission><formData><coverPageHeader>')
    assert parsed["parsed_ok"] is False
    assert parsed["error"]
    assert parsed["holder_name"] is None
    assert parsed["aggregate_shares"] is None
    assert parsed["percent_of_class"] is None
    assert parsed["snapshot_date"] is None


def test_parse_empty_document_never_invents():
    parsed = parse_schedule13dg("")
    assert parsed["parsed_ok"] is False
    assert parsed["aggregate_shares"] is None


def test_parse_html_document_never_invents():
    parsed = parse_schedule13dg(HTML_BODY + "<body>SEC schedule</body></html>")
    assert parsed["parsed_ok"] is False
    assert parsed["holder_name"] is None


# ---------------- Portada SGML heredada ----------------

LEGACY_13G = """<SEC-DOCUMENT>0000932471-24-000884.txt : 20241112
<SEC-HEADER>0000932471-24-000884.hdr.sgml : 20241112
<ACCEPTANCE-DATETIME>20241112051234
CONFORMED SUBMISSION TYPE: SC 13G/A
</SEC-HEADER>
<DOCUMENT>
<TYPE>SC 13G/A
<TEXT>
CUSIP No. 00217D100

1 NAME OF REPORTING PERSON
I.R.S. IDENTIFICATION NOS. OF ABOVE PERSONS (ENTITIES ONLY)
Example Capital Management LLC

7 SOLE VOTING POWER
1,000,000

8 SHARED VOTING POWER
0

9 SOLE DISPOSITIVE POWER
1,000,000

10 SHARED DISPOSITIVE POWER
0

11 AGGREGATE AMOUNT BENEFICIALLY OWNED BY EACH REPORTING PERSON
1,000,000

13 PERCENT OF CLASS REPRESENTED BY AMOUNT IN ROW 11
6.2%

Date of Event Which Requires Filing of this Statement
09/30/2024
</TEXT>
</DOCUMENT>
</SEC-DOCUMENT>"""


def test_parse_legacy_sgml_cover_page():
    parsed = parse_schedule13dg(LEGACY_13G)
    assert parsed["format"] == "legacy-text"
    assert parsed["parsed_ok"] is True
    assert parsed["form"] == "SC 13G/A"
    assert parsed["is_amendment"] is True
    assert parsed["holder_name"] == "Example Capital Management LLC"
    assert parsed["aggregate_shares"] == 1000000
    assert parsed["percent_of_class"] == 6.2
    assert parsed["snapshot_date"] == "2024-09-30"
    assert parsed["cusip"] == "00217D100"


def test_parse_legacy_garbage_never_invents():
    parsed = parse_schedule13dg("CONFORMED SUBMISSION TYPE: SC 13D\n\nsome prose without labels\n")
    assert parsed["parsed_ok"] is False
    assert parsed["error"]
    assert parsed["holder_name"] is None
    assert parsed["aggregate_shares"] is None


# ---------------- Documento crudo vs renderizado ----------------


def test_raw_document_url_strips_rendered_xsl_segment():
    assert raw_document_url(RENDERED) == RAW


def test_raw_document_url_leaves_plain_urls_untouched():
    assert raw_document_url(RAW) == RAW


def test_fetch_returns_document_served_directly():
    client = _FakeClient({RAW: REAL_13G_XML})
    assert fetch_filing_document(RAW, client=client) == REAL_13G_XML
    assert client.requested == [RAW]


def test_fetch_falls_back_to_raw_document_when_served_rendered_html():
    client = _FakeClient({RENDERED: HTML_BODY, RAW: REAL_13G_XML})
    assert fetch_filing_document(RENDERED, client=client) == REAL_13G_XML
    assert client.requested == [RENDERED, RAW]


def test_fetch_raises_when_raw_variant_is_also_html():
    client = _FakeClient({RENDERED: HTML_BODY, RAW: HTML_BODY})
    with pytest.raises(ValueError, match="HTML"):
        fetch_filing_document(RENDERED, client=client)


def test_fetch_rejects_non_sec_host():
    with pytest.raises(ValueError, match="sec.gov"):
        fetch_filing_document("https://evil.example.com/primary_doc.xml", client=_FakeClient({}))


# ---------------- Listado por CIK ----------------


def test_recent_form13dg_filings_filters_both_form_families():
    payload = {
        "filings": {
            "recent": {
                "accessionNumber": [
                    "0002012383-26-003748",
                    "0001493152-26-029689",
                    "0000000000-26-000001",
                    "0000932471-24-000884",
                    "0000000000-26-000002",
                ],
                "form": ["SCHEDULE 13G", "SC 13D/A", "10-K", "SC 13G/A", "4"],
                "filingDate": ["2026-10-27", "2026-06-23", "2026-02-10", "2024-11-12", "2024-01-01"],
                "reportDate": ["2026-09-30", "2026-06-15", "2025-12-31", "2024-09-30", "2023-12-31"],
                "primaryDocument": [
                    "xslSCHEDULE_13G_X02/primary_doc.xml",
                    "xslSCHEDULE_13D_X02/primary_doc.xml",
                    "asts-20251231.htm",
                    "UnitedStates_13G__ASTSpaceMo.txt",
                    "form4.xml",
                ],
            }
        }
    }
    import json

    url = "https://data.sec.gov/submissions/CIK0001780312.json"
    client = _FakeClient({url: json.dumps(payload)})
    filings = recent_form13dg_filings("1780312", client=client)
    assert [f["form"] for f in filings] == ["SCHEDULE 13G", "SC 13D/A", "SC 13G/A"]
    first = filings[0]
    assert first["accession_number"] == "0002012383-26-003748"
    assert first["filing_date"] == "2026-10-27"
    assert first["report_date"] == "2026-09-30"
    assert first["index_url"] == "https://www.sec.gov/Archives/edgar/data/1780312/000201238326003748/"
    assert first["document_url"].endswith("xslSCHEDULE_13G_X02/primary_doc.xml")
