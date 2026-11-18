"""Conector Form 144: parseo del XML real de EDGAR y URL cruda.

Fixtures reales (descargadas de sec.gov el 2026-11-18):
- slgn_0000849869-26-000005.xml: SLGN, directora, 11 adquisiciones RSU +
  1 compra en mercado, sin ventas en 3 meses, sin plan 10b5-1.
- aura_0001997710-26-000007.xml: AURA, officer, presentado bajo el CIK de
  la vendedora pero listado en las submissions del emisor; remarks de
  sell-to-cover (venta no discrecional para retencion fiscal).
- aura_0001950047-24-007810.xml: AURA, con planAdoptionDate (10b5-1).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.connectors import form144

FIXTURES = Path(__file__).parent / "fixtures" / "form144"
SLGN_XML = (FIXTURES / "slgn_0000849869-26-000005.xml").read_text(encoding="utf-8")
AURA_XML = (FIXTURES / "aura_0001997710-26-000007.xml").read_text(encoding="utf-8")
AURA_PLAN_XML = (FIXTURES / "aura_0001950047-24-007810.xml").read_text(encoding="utf-8")


def test_parse_real_slgn_notice():
    parsed = form144.parse_form144_xml(SLGN_XML)
    assert parsed["parsed_ok"] is True
    assert parsed["submission_type"] == "144"
    assert parsed["issuer_cik"] == "0000849869"
    assert parsed["issuer_name"] == "SILGAN HOLDINGS INC"
    assert parsed["seller_cik"] == "0001164469"
    assert parsed["seller_name"] == "LEWIS ROBERT B"
    assert parsed["relationships"] == ["Director"]
    assert len(parsed["securities"]) == 1
    security = parsed["securities"][0]
    assert security["shares"] == 88861
    assert security["market_value"] == 3687731.50
    assert security["shares_outstanding"] == 105682020
    assert security["approx_sale_date"] == "11/16/2026"
    assert security["exchange"] == "NYSE"
    assert security["broker_name"] == "FSC Securities Corporation"
    # 11 bloques de adquisicion (10 RSU al Issuer + 1 compra en mercado).
    assert len(parsed["acquisitions"]) == 11
    market_buy = parsed["acquisitions"][-1]
    assert market_buy["nature_of_acquisition"] == "Open Market Purchase"
    assert market_buy["acquired_from"] == "Open Market"
    assert market_buy["shares_acquired"] == 7020
    assert market_buy["nature_of_payment"] == "Cash"
    assert parsed["nothing_to_report_past_3m"] is True
    assert parsed["sales_past_3m"] == []
    assert parsed["plan_adoption_dates"] == []
    assert parsed["notice_date"] == "11/13/2026"


def test_parse_real_aura_sell_to_cover_remarks():
    parsed = form144.parse_form144_xml(AURA_XML)
    assert parsed["parsed_ok"] is True
    assert parsed["issuer_cik"] == "0001501796"
    assert parsed["seller_cik"] == "0001997710"
    assert parsed["seller_name"] == "Janet Jill Hopkins"
    assert parsed["relationships"] == ["Officer"]
    assert parsed["securities"][0]["shares"] == 16903
    assert parsed["securities"][0]["market_value"] == 119167
    assert "sell-to-cover" in (parsed["remarks"] or "")


def test_parse_real_plan_adoption_date_10b5_1():
    parsed = form144.parse_form144_xml(AURA_PLAN_XML)
    assert parsed["parsed_ok"] is True
    assert parsed["seller_name"] == "JULIE FEDER"
    assert parsed["plan_adoption_dates"] == ["06/23/2023"]


def test_parse_rejects_non_144_xml():
    parsed = form144.parse_form144_xml("<div>AccessDenied</div>")
    assert parsed["parsed_ok"] is False
    assert parsed["error"] is not None
    parsed = form144.parse_form144_xml("<?xml version='1.0'?><broken")
    assert parsed["parsed_ok"] is False
    # Un XML valido de otro esquema (Form 4) no se acepta como 144.
    parsed = form144.parse_form144_xml(
        '<?xml version="1.0"?><ownershipDocument><issuer></issuer></ownershipDocument>'
    )
    assert parsed["parsed_ok"] is False


def test_missing_fields_stay_none_never_invented():
    parsed = form144.parse_form144_xml(
        '<?xml version="1.0"?><edgarSubmission xmlns="http://www.sec.gov/edgar/ownership">'
        "<headerData><submissionType>144</submissionType></headerData>"
        "<formData><issuerInfo><issuerCik>0000000001</issuerCik></issuerInfo></formData>"
        "</edgarSubmission>"
    )
    assert parsed["parsed_ok"] is True
    assert parsed["issuer_cik"] == "0000000001"
    assert parsed["seller_name"] is None
    assert parsed["securities"] == []
    totals = form144.proposed_sale_totals(parsed)
    assert totals["shares_to_sell"] is None
    assert totals["aggregate_market_value"] is None
    assert totals["approx_sale_date"] is None


def test_totals_are_none_when_any_block_is_missing_the_figure():
    parsed = form144.parse_form144_xml(SLGN_XML)
    totals = form144.proposed_sale_totals(parsed)
    assert totals["shares_to_sell"] == 88861
    assert totals["aggregate_market_value"] == 3687731.50
    # Un segundo bloque sin market_value: el total no se publica (nunca un
    # subtotal presentado como total).
    parsed["securities"].append(
        {
            "securities_class_title": "Common Stock",
            "broker_name": None,
            "shares": 100,
            "market_value": None,
            "shares_outstanding": 105682020,
            "approx_sale_date": "11/16/2026",
            "exchange": "NYSE",
        }
    )
    totals = form144.proposed_sale_totals(parsed)
    assert totals["aggregate_market_value"] is None
    assert totals["shares_to_sell"] == 88961


def test_raw_document_url_unwraps_rendered_variant():
    rendered = (
        "https://www.sec.gov/Archives/edgar/data/849869/000084986926000005/"
        "xsl144X01/primary_doc.xml"
    )
    assert form144.raw_document_url(rendered) == (
        "https://www.sec.gov/Archives/edgar/data/849869/000084986926000005/primary_doc.xml"
    )
    raw = "https://www.sec.gov/Archives/edgar/data/849869/000084986926000005/primary_doc.xml"
    assert form144.raw_document_url(raw) == raw


def test_fetch_rejects_non_sec_hosts():
    with pytest.raises(ValueError):
        form144.fetch_filing_xml("https://evil.example.com/primary_doc.xml")


def test_recent_filings_filters_form_144_family():
    payload = {
        "filings": {
            "recent": {
                "accessionNumber": [
                    "0000849869-26-000005",
                    "0000849869-26-000006",
                    "0000849869-26-000007",
                ],
                "form": ["144", "144/A", "8-K"],
                "filingDate": ["2026-11-13", "2026-11-14", "2026-11-14"],
                "reportDate": ["", "", ""],
                "primaryDocument": [
                    "xsl144X01/primary_doc.xml",
                    "xsl144X01/primary_doc.xml",
                    "d8k.htm",
                ],
            }
        }
    }

    class _Resp:
        status_code = 200
        text = json.dumps(payload)

        def raise_for_status(self):
            return None

        def json(self):
            return payload

    class _Client:
        def get(self, url, headers=None):
            assert url == "https://data.sec.gov/submissions/CIK0000849869.json"
            return _Resp()

    filings = form144.recent_form144_filings("0000849869", client=_Client())
    assert [f["form"] for f in filings] == ["144", "144/A"]
    assert filings[0]["document_url"].endswith("xsl144X01/primary_doc.xml")
