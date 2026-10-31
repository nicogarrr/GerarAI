"""Cableado al registry de salud de Form 4, Form 13F y SC 13D/G (SEC, sync).

Fulfills: VAL-DATA-004 (extensión a conectores de insiders sobre SEC)
Expected Behavior:
- Comparten la clave "sec_edgar" (mismo proveedor): 5xx/403/429/red/no-JSON
  degradan; 400/404 (CIK o documento inexistente) NO degradan; éxito cierra
"""

from __future__ import annotations

import httpx
import pytest

from app.services.connectors import form4, form13dg, form13f
from app.services.data_source_health import DataSourceHealthRegistry, get_data_source_registry


@pytest.fixture(autouse=True)
def fresh_registry():
    DataSourceHealthRegistry._instance = None
    yield
    DataSourceHealthRegistry._instance = None


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _json(status: int, body: str = "{}") -> httpx.Response:
    return httpx.Response(status, text=body, headers={"content-type": "application/json"})


_SUBMISSIONS_EMPTY = '{"filings":{"recent":{"accessionNumber":[]}}}'


def test_form4_submissions_500_degrada():
    def handler(request):
        return _json(500)

    registry = get_data_source_registry()
    before = registry.get_status("sec_edgar").consecutive_failures
    with pytest.raises(httpx.HTTPStatusError):
        form4.recent_form4_filings("320193", client=_client(handler))
    assert registry.get_status("sec_edgar").consecutive_failures == before + 1


def test_form4_submissions_404_cik_no_degrada():
    def handler(request):
        return _json(404)

    registry = get_data_source_registry()
    before = registry.get_status("sec_edgar").consecutive_failures
    with pytest.raises(httpx.HTTPStatusError):
        form4.recent_form4_filings("9999999999", client=_client(handler))
    assert registry.get_status("sec_edgar").consecutive_failures == before


def test_form4_submissions_exito_cierra():
    def handler(request):
        return _json(200, _SUBMISSIONS_EMPTY)

    registry = get_data_source_registry()
    registry.record_failure("sec_edgar", "fallo previo")
    items = form4.recent_form4_filings("320193", client=_client(handler))
    assert items == []
    assert registry.get_status("sec_edgar").consecutive_failures == 0


def test_form4_get_text_red_caida_degrada():
    def handler(request):
        raise httpx.ConnectError("down", request=request)

    registry = get_data_source_registry()
    before = registry.get_status("sec_edgar").consecutive_failures
    with pytest.raises(httpx.ConnectError):
        form4._get_text("https://www.sec.gov/Archives/edgar/data/320193/x.xml", _client(handler))
    assert registry.get_status("sec_edgar").consecutive_failures == before + 1


def test_form4_get_text_404_documento_no_degrada():
    def handler(request):
        return httpx.Response(404, text="")

    registry = get_data_source_registry()
    before = registry.get_status("sec_edgar").consecutive_failures
    with pytest.raises(httpx.HTTPStatusError):
        form4._get_text("https://www.sec.gov/Archives/edgar/data/320193/x.xml", _client(handler))
    assert registry.get_status("sec_edgar").consecutive_failures == before


def test_form13f_500_degrada():
    def handler(request):
        return _json(500)

    registry = get_data_source_registry()
    before = registry.get_status("sec_edgar").consecutive_failures
    with pytest.raises(httpx.HTTPStatusError):
        form13f.fetch_information_table(
            "https://www.sec.gov/Archives/edgar/data/1/x.xml", client=_client(handler)
        )
    assert registry.get_status("sec_edgar").consecutive_failures == before + 1


def test_form13f_exito_cierra():
    xml = '<?xml version="1.0"?><informationTable><infoTable><nameOfIssuer>X</nameOfIssuer></infoTable></informationTable>'

    def handler(request):
        return httpx.Response(200, text=xml)

    registry = get_data_source_registry()
    registry.record_failure("sec_edgar", "fallo previo")
    rows = form13f.fetch_information_table(
        "https://www.sec.gov/Archives/edgar/data/1/x.xml", client=_client(handler)
    )
    assert isinstance(rows, list)
    assert registry.get_status("sec_edgar").consecutive_failures == 0


def test_form13dg_submissions_500_degrada():
    def handler(request):
        return _json(500)

    registry = get_data_source_registry()
    before = registry.get_status("sec_edgar").consecutive_failures
    with pytest.raises(httpx.HTTPStatusError):
        form13dg.recent_form13dg_filings("320193", client=_client(handler))
    assert registry.get_status("sec_edgar").consecutive_failures == before + 1


def test_form13dg_submissions_exito_cierra():
    def handler(request):
        return _json(200, _SUBMISSIONS_EMPTY)

    registry = get_data_source_registry()
    registry.record_failure("sec_edgar", "fallo previo")
    items = form13dg.recent_form13dg_filings("320193", client=_client(handler))
    assert items == []
    assert registry.get_status("sec_edgar").consecutive_failures == 0


def test_form13f_200_no_json_degrada():
    """Un 200 con challenge HTML en submissions NO cierra el circuito."""

    def handler(request):
        return httpx.Response(200, text="<!DOCTYPE html><html><body>challenge</body></html>")

    registry = get_data_source_registry()
    before = registry.get_status("sec_edgar").consecutive_failures
    with pytest.raises(ValueError):
        form13f.recent_13f_filings("1067983", client=_client(handler))
    assert registry.get_status("sec_edgar").consecutive_failures == before + 1


def test_form13f_documento_200_html_degrada():
    """Un 200 HTML donde iba el information table XML tampoco es éxito."""

    def handler(request):
        return httpx.Response(200, text="<html><head><title>Request Rejected</title></head></html>")

    registry = get_data_source_registry()
    before = registry.get_status("sec_edgar").consecutive_failures
    with pytest.raises(Exception):
        form13f.fetch_information_table(
            "https://www.sec.gov/Archives/edgar/data/1/x.xml", client=_client(handler)
        )
    assert registry.get_status("sec_edgar").consecutive_failures == before + 1


def test_form4_documento_200_html_challenge_degrada():
    def handler(request):
        return httpx.Response(200, text="<!DOCTYPE html><html><body>challenge</body></html>")

    registry = get_data_source_registry()
    before = registry.get_status("sec_edgar").consecutive_failures
    with pytest.raises(ValueError):
        form4.fetch_filing_xml(
            "https://www.sec.gov/Archives/edgar/data/320193/000032019326000123/doc4.xml",
            client=_client(handler),
        )
    assert registry.get_status("sec_edgar").consecutive_failures == before + 1


def test_form4_documento_xml_valido_cierra():
    xml = '<?xml version="1.0"?><ownershipDocument><issuer></issuer></ownershipDocument>'

    def handler(request):
        return httpx.Response(200, text=xml)

    registry = get_data_source_registry()
    registry.record_failure("sec_edgar", "fallo previo")
    text = form4.fetch_filing_xml(
        "https://www.sec.gov/Archives/edgar/data/320193/000032019326000123/doc4.xml", client=_client(handler)
    )
    assert "ownershipDocument" in text
    assert registry.get_status("sec_edgar").consecutive_failures == 0


def test_form13dg_documento_200_html_challenge_degrada():
    def handler(request):
        return httpx.Response(200, text="<html><body>Access Denied</body></html>")

    registry = get_data_source_registry()
    before = registry.get_status("sec_edgar").consecutive_failures
    with pytest.raises(ValueError):
        form13dg.fetch_filing_document(
            "https://www.sec.gov/Archives/edgar/data/320193/0000320193/sc13g.htm", client=_client(handler)
        )
    assert registry.get_status("sec_edgar").consecutive_failures == before + 1


def test_form13dg_documento_sgml_legitimo_cierra():
    sgml = "<SEC-DOCUMENT>0000320193-26-000123\nCONFORMED SUBMISSION TYPE: SC 13G\n<TEXT>\nresto\n"

    def handler(request):
        return httpx.Response(200, text=sgml)

    registry = get_data_source_registry()
    registry.record_failure("sec_edgar", "fallo previo")
    text = form13dg.fetch_filing_document(
        "https://www.sec.gov/Archives/edgar/data/320193/0000320193/sc13g.htm", client=_client(handler)
    )
    assert "SC 13G" in text
    assert registry.get_status("sec_edgar").consecutive_failures == 0


def test_form4_documento_xml_malformado_degrada():
    def handler(request):
        return httpx.Response(200, text='<?xml version="1.0"?><broken')

    registry = get_data_source_registry()
    before = registry.get_status("sec_edgar").consecutive_failures
    with pytest.raises(ValueError):
        form4.fetch_filing_xml(
            "https://www.sec.gov/Archives/edgar/data/320193/000032019326000123/doc4.xml",
            client=_client(handler),
        )
    assert registry.get_status("sec_edgar").consecutive_failures == before + 1


def test_form4_documento_xml_bien_formado_raiz_ajena_degrada():
    def handler(request):
        return httpx.Response(200, text="<div>AccessDenied</div>")

    registry = get_data_source_registry()
    before = registry.get_status("sec_edgar").consecutive_failures
    with pytest.raises(ValueError):
        form4.fetch_filing_xml(
            "https://www.sec.gov/Archives/edgar/data/320193/000032019326000123/doc4.xml",
            client=_client(handler),
        )
    assert registry.get_status("sec_edgar").consecutive_failures == before + 1


def test_form13dg_documento_xml_raiz_ajena_degrada():
    def handler(request):
        return httpx.Response(200, text="<div>AccessDenied</div>")

    registry = get_data_source_registry()
    before = registry.get_status("sec_edgar").consecutive_failures
    with pytest.raises(ValueError):
        form13dg.fetch_filing_document(
            "https://www.sec.gov/Archives/edgar/data/320193/0000320193/sc13g.xml", client=_client(handler)
        )
    assert registry.get_status("sec_edgar").consecutive_failures == before + 1


def test_form13f_submissions_json_lista_degrada():
    def handler(request):
        return httpx.Response(200, json=[1, 2, 3])

    registry = get_data_source_registry()
    before = registry.get_status("sec_edgar").consecutive_failures
    with pytest.raises(ValueError):
        form13f.recent_13f_filings("1067983", client=_client(handler))
    assert registry.get_status("sec_edgar").consecutive_failures == before + 1


def test_form13f_submissions_json_objeto_vacio_degrada():
    def handler(request):
        return httpx.Response(200, json={})

    registry = get_data_source_registry()
    before = registry.get_status("sec_edgar").consecutive_failures
    with pytest.raises(ValueError):
        form13f.recent_13f_filings("1067983", client=_client(handler))
    assert registry.get_status("sec_edgar").consecutive_failures == before + 1


def test_form13f_index_json_sin_directory_degrada():
    def handler(request):
        return httpx.Response(200, json={"otra": "cosa"})

    registry = get_data_source_registry()
    before = registry.get_status("sec_edgar").consecutive_failures
    with pytest.raises(ValueError):
        form13f.information_table_url("1067983", "0000950123-26-001234", None, client=_client(handler))
    assert registry.get_status("sec_edgar").consecutive_failures == before + 1
