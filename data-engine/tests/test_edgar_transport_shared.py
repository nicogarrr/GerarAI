"""El transporte EDGAR de form4 y form13dg es el MISMO codigo (edgar_common).

Antes form13dg era un "espejo" de form4 mantenido a mano; estos tests fijan
que el espejo ahora es por construccion (identidad de objetos) y que los dos
wrappers comparten la mecanica de listado filtrando solo por su familia de
formularios.
"""

from __future__ import annotations

from app.services.connectors import edgar_common, form4, form13dg


def test_transport_objects_are_shared_by_identity():
    for name in (
        "SUBMISSIONS_URL",
        "ARCHIVES_URL",
        "MIN_INTERVAL_SECONDS",
        "RETRY_STATUSES",
        "RETRY_BACKOFF_SECONDS",
        "resolve_user_agent",
        "default_headers",
        "filing_index_url",
        "_throttle",
        "_record_sec_outcome",
        "_record_sec_http_failure",
        "_record_sec_transport_failure",
    ):
        assert getattr(form4, name) is getattr(edgar_common, name), name
        assert getattr(form13dg, name) is getattr(edgar_common, name), name


class _FakeResponse:
    def __init__(self, payload: str):
        self.text = payload

    def raise_for_status(self) -> None:
        return None

    def json(self):
        import json

        return json.loads(self.text)


class _FakeClient:
    def __init__(self, payload: str):
        self.payload = payload
        self.requested: list[str] = []

    def get(self, url: str, headers: dict | None = None) -> _FakeResponse:
        self.requested.append(url)
        return _FakeResponse(self.payload)


MIXED_SUBMISSIONS = """{
  "filings": {"recent": {
    "accessionNumber": ["0001-26-000001", "0001-26-000002", "0001-26-000003", "0001-26-000004"],
    "form": ["4", "SC 13G", "10-K", "4/A"],
    "filingDate": ["2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04"],
    "reportDate": ["2026-09-30", "2026-09-30", "2026-09-30", "2026-10-01"],
    "primaryDocument": ["f4.xml", "primary_doc.xml", "d10k.htm", "f4a.xml"]
  }}
}"""


def test_wrappers_share_listing_and_filter_by_form_family():
    client4 = _FakeClient(MIXED_SUBMISSIONS)
    client13 = _FakeClient(MIXED_SUBMISSIONS)

    filings4 = form4.recent_form4_filings("1780312", client=client4)
    filings13 = form13dg.recent_form13dg_filings("1780312", client=client13)

    assert [f["form"] for f in filings4] == ["4", "4/A"]
    assert [f["form"] for f in filings13] == ["SC 13G"]
    # Misma mecanica: misma URL de submissions y mismas URLs construidas.
    assert client4.requested == client13.requested
    assert filings4[0]["index_url"] == ("https://www.sec.gov/Archives/edgar/data/1780312/000126000001/")
    assert filings13[0]["document_url"].endswith("/000126000002/primary_doc.xml")
    # Mismas claves de salida en los dos wrappers.
    assert set(filings4[0]) == set(filings13[0])


def test_form13f_reuses_same_source_health_and_urls():
    from app.services.connectors import form13f

    for name in ("SUBMISSIONS_URL", "ARCHIVES_URL", "default_headers", "filing_index_url",
                 "_record_sec_outcome", "_record_sec_http_failure", "_record_sec_transport_failure"):
        assert getattr(form13f, name) is getattr(edgar_common, name)
