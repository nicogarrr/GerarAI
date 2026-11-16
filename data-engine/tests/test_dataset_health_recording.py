"""Los jobs de datasets SEC (13F y N-PORT) registran su salud (fix7b).

La descarga vive en los servicios (los conectores *_dataset son puro
parseo, sin red): exito al completar o confirmar sin cambios, fallo si la
pagina de la SEC no lista ficheros o si la pasada rompe. Las guardas
locales (sin CUSIP verificado en el universo) no degradan.
"""

from __future__ import annotations

import httpx
import pytest

from app.services import fund_holders as fh
from app.services import institutional_holders as ih
from tests import test_fund_holders as tfh
from tests import test_institutional_holders as tih


class _Registry:
    def __init__(self):
        self.successes = []
        self.failures = []

    def record_success(self, key, elapsed_ms=0.0):
        self.successes.append((key, elapsed_ms))

    def record_failure(self, key, error):
        self.failures.append((key, error))


@pytest.fixture
def registry(monkeypatch):
    reg = _Registry()
    monkeypatch.setattr(ih, "get_data_source_registry", lambda: reg)
    monkeypatch.setattr(fh, "get_data_source_registry", lambda: reg)
    return reg


_HTML_13F = ('<a href="/files/a/01mar2026-31may2026_form13f.zip">x</a>'
             '<a href="/files/a/01jun2026-31aug2026_form13f.zip">y</a>')
_HTML_NPORT = ('<a href="/files/dera/data/form-n-port-data-sets/2026q2_nport.zip">a</a>'
               '<a href="/files/dera/data/form-n-port-data-sets/2026q3_nport.zip">b</a>')


def test_13f_exito_y_sin_cambios_registran_success(registry):
    q2, q1 = tih._datasets()

    def handler(request):
        url = str(request.url)
        if url == ih.ds.DATASETS_PAGE:
            return httpx.Response(200, text=_HTML_13F)
        return httpx.Response(200, content=(q2 if "jun2026" in url else q1).getvalue())

    db = tih._db()
    out = ih.refresh_institutional_holders(db, httpx.Client(transport=httpx.MockTransport(handler)))
    assert out["status"] == "ok"
    again = ih.refresh_institutional_holders(db, httpx.Client(transport=httpx.MockTransport(handler)))
    assert again["status"] == "sin_cambios"
    assert [k for k, _ in registry.successes] == ["form13f_dataset", "form13f_dataset"]
    assert registry.failures == []


def test_13f_pagina_sin_ficheros_y_error_registran_failure(registry):
    def handler_vacia(request):
        return httpx.Response(200, text="<html>sin enlaces</html>")

    db = tih._db()
    out = ih.refresh_institutional_holders(db, httpx.Client(transport=httpx.MockTransport(handler_vacia)))
    assert out["status"] == "sin_datos"
    assert [k for k, _ in registry.failures] == ["form13f_dataset"]

    def handler_roto(request):
        raise httpx.ConnectError("sin red")

    out = ih.refresh_institutional_holders(tih._db(), httpx.Client(transport=httpx.MockTransport(handler_roto)))
    assert out["status"] == "error"
    assert [k for k, _ in registry.failures] == ["form13f_dataset", "form13f_dataset"]
    assert registry.successes == []


def test_nport_exito_y_sin_cambios_registran_success(registry):
    body = tfh._zip().getvalue()

    def handler(request):
        return httpx.Response(200, text=_HTML_NPORT) if str(request.url) == fh.nport.DATASETS_PAGE else httpx.Response(200, content=body)

    db = tfh._db()
    out = fh.refresh_fund_holders(db, httpx.Client(transport=httpx.MockTransport(handler)))
    assert out["status"] == "ok"
    again = fh.refresh_fund_holders(db, httpx.Client(transport=httpx.MockTransport(handler)))
    assert again["status"] == "sin_cambios"
    assert [k for k, _ in registry.successes] == ["form_nport_dataset", "form_nport_dataset"]
    assert registry.failures == []


def test_nport_pagina_sin_ficheros_y_error_registran_failure(registry):
    def handler_vacia(request):
        return httpx.Response(200, text="<html>sin enlaces</html>")

    out = fh.refresh_fund_holders(tfh._db(), httpx.Client(transport=httpx.MockTransport(handler_vacia)))
    assert out["status"] == "sin_datos"
    assert [k for k, _ in registry.failures] == ["form_nport_dataset"]

    def handler_roto(request):
        raise httpx.ConnectError("sin red")

    out = fh.refresh_fund_holders(tfh._db(), httpx.Client(transport=httpx.MockTransport(handler_roto)))
    assert out["status"] == "error"
    assert [k for k, _ in registry.failures] == ["form_nport_dataset", "form_nport_dataset"]


def test_sin_cusip_universo_no_degrada(registry):
    """Sin empresas con CUSIP verificado la pasada ni siquiera empieza: guarda local."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.models.entities import Base

    db = Session(create_engine("sqlite://"))
    Base.metadata.create_all(db.get_bind())

    def handler(request):
        return httpx.Response(200, text=_HTML_13F if str(request.url) == ih.ds.DATASETS_PAGE else _HTML_NPORT)

    assert ih.refresh_institutional_holders(db, httpx.Client(transport=httpx.MockTransport(handler)))["status"] == "sin_datos"
    assert fh.refresh_fund_holders(db, httpx.Client(transport=httpx.MockTransport(handler)))["status"] == "sin_datos"
    assert registry.failures == [] and registry.successes == []


def _zip_vacio():
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name in ("SUBMISSION.tsv", "REGISTRANT.tsv", "FUND_REPORTED_INFO.tsv", "FUND_REPORTED_HOLDING.tsv",
                     "COVERPAGE.tsv", "INFOTABLE.tsv", "SUMMARYPAGE.tsv"):
            zf.writestr(name, "COL\n")
    buf.seek(0)
    return buf


def test_13f_dataset_ilegible_no_afirma_salud_ni_fija_etag(registry):
    """ZIP descargado (200) pero sin informes válidos = parseador/formato roto:
    no es una ausencia observada; no se registra éxito ni se fija el ETag."""

    def handler(request):
        url = str(request.url)
        if url == ih.ds.DATASETS_PAGE:
            return httpx.Response(200, text=_HTML_13F)
        return httpx.Response(200, content=_zip_vacio().getvalue(), headers={"etag": '"v1"'})

    db = tih._db()
    out = ih.refresh_institutional_holders(db, httpx.Client(transport=httpx.MockTransport(handler)))
    assert out["status"] == "sin_datos"
    assert registry.successes == []
    assert [k for k, _ in registry.failures] == ["form13f_dataset"]
    assert db.scalars(__import__("sqlalchemy").select(__import__("app.models.entities", fromlist=["ConnectorState"]).ConnectorState)).first() is None


def test_nport_dataset_ilegible_no_afirma_salud_ni_fija_etag(registry):
    def handler(request):
        if str(request.url) == fh.nport.DATASETS_PAGE:
            return httpx.Response(200, text=_HTML_NPORT)
        return httpx.Response(200, content=_zip_vacio().getvalue(), headers={"etag": '"v1"'})

    db = tfh._db()
    out = fh.refresh_fund_holders(db, httpx.Client(transport=httpx.MockTransport(handler)))
    assert out["status"] == "sin_datos"
    assert registry.successes == []
    assert [k for k, _ in registry.failures] == ["form_nport_dataset"]
