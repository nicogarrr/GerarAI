"""Descarga de históricos con respuestas locales: ventana, páginas, fallos y fallback."""

import json
from datetime import date

from app.services import guidance_backfill as svc
from app.services.connectors import form4
from app.services.connectors.edgar_common import SUBMISSIONS_URL, filing_index_url

TODAY = date(2026, 11, 9)


def _page(accessions, dates):
    return {
        "accessionNumber": accessions,
        "filingDate": dates,
        "form": ["8-K"] * len(accessions),
        "items": ["2.02"] * len(accessions),
    }


def test_descarga_paginas_ventana_errores_y_orden():
    accs = [f"0000000001-25-{i:06d}" for i in range(1, 5)]
    sub = {
        "filings": {
            "recent": _page(accs[:3], ["2025-04-01", "2025-05-01", "2025-06-01"]),
            "files": [
                {"filingTo": "2019-12-31", "name": "too-old.json"},
                {"filingTo": "2024-12-31"},
                {"filingTo": "2024-12-31", "name": "older.json"},
            ],
        }
    }
    root = SUBMISSIONS_URL.format(cik="0000000001")
    older = "https://data.sec.gov/submissions/older.json"
    urls = {root: json.dumps(sub), older: json.dumps(_page(accs[3:], ["2024-06-01"]))}
    docurl = "https://www.sec.gov/Archives/edgar/data/1/ok.htm"
    index = '<a href="/Archives/edgar/data/1/ok.htm">doc</a></td><td scope="row">EX-99.1</td>'
    for acc in (accs[0], accs[3]):
        urls[filing_index_url("1", acc) + acc + "-index.htm"] = index
    urls[filing_index_url("1", accs[1]) + accs[1] + "-index.htm"] = "<p>sin anexo</p>"
    urls[docurl] = "<style>hidden</style><p>Revenue &amp; guidance</p>"
    called = []

    def get(url):
        called.append(url)
        return urls[url]  # tercer índice falla: se cuenta y sigue, sin red

    out = svc.fetch_documents("1", today=TODAY, get_text=get)
    assert out == {
        "filings": 4,
        "misses": 2,
        "documents": [
            (date(2024, 6, 1), docurl, " Revenue & guidance. "),
            (date(2025, 4, 1), docurl, " Revenue & guidance. "),
        ],
    }
    assert older in called
    assert not any("too-old" in url for url in called)
    assert called.count(docurl) == 2


def test_get_por_defecto_delega_form4_y_sin_filings(monkeypatch):
    calls = []

    def get(url, client):
        calls.append((url, client))
        return "{}"

    monkeypatch.setattr(form4, "_get_text", get)
    assert svc.fetch_documents(1, today=TODAY) == {"filings": 0, "documents": [], "misses": 0}
    assert calls == [(SUBMISSIONS_URL.format(cik="0000000001"), None)]
