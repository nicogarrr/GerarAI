"""El salto de los datasets SEC no vale solo por URL: republicar el mismo ZIP
con contenido corregido (otro ETag) fuerza recalculo (Lote 2, hallazgo 3).

El ETag del ZIP procesado se guarda en ConnectorState (fila global). Sin
ETag (HEAD falla o no lo sirve) se conserva el comportamiento anterior.
"""

from __future__ import annotations

import httpx
from sqlalchemy import select

from app.models.entities import ConnectorState
from app.services import fund_holders as fh
from app.services import institutional_holders as ih
from tests import test_institutional_holders as tih

_HTML_13F = ('<a href="/files/a/01mar2026-31may2026_form13f.zip">x</a>'
             '<a href="/files/a/01jun2026-31aug2026_form13f.zip">')


def _handler_13f(etag, calls, fail_head=False):
    q2, q1 = tih._datasets()

    def handler(request):
        url = str(request.url)
        calls.append((request.method, url))
        if fail_head and request.method == "HEAD":
            return httpx.Response(500)
        if url == ih.ds.DATASETS_PAGE:
            return httpx.Response(200, text=_HTML_13F)
        if request.method == "HEAD":
            return httpx.Response(200, headers={"etag": etag})
        return httpx.Response(200, content=(q2 if "jun2026" in url else q1).getvalue(),
                              headers={"etag": etag})

    return handler


def _estado(db, url):
    return db.scalars(select(ConnectorState).where(
        ConnectorState.connector == "form13f_dataset",
        ConnectorState.feed_url == url)).first()


def test_primer_job_guarda_etag_y_segundo_no_descarga():
    calls = []
    db = tih._db()
    client = httpx.Client(transport=httpx.MockTransport(_handler_13f('"v1"', calls)))
    out = ih.refresh_institutional_holders(db, client)
    assert out["status"] == "ok"
    zip_url = [u for m, u in calls if "jun2026" in u and m == "GET"][0]
    assert _estado(db, zip_url).etag == '"v1"'

    calls.clear()
    again = ih.refresh_institutional_holders(db, client)
    assert again["status"] == "sin_cambios"
    # Pagina + HEAD del ZIP vigente; ninguna descarga.
    assert [m for m, _ in calls] == ["GET", "HEAD"]


def test_mismo_url_con_otro_etag_fuerza_recalculo():
    calls = []
    db = tih._db()
    out = ih.refresh_institutional_holders(db, httpx.Client(transport=httpx.MockTransport(_handler_13f('"v1"', calls))))
    assert out["status"] == "ok"

    calls.clear()
    # La SEC republica el mismo ZIP corregido: otro ETag.
    client2 = httpx.Client(transport=httpx.MockTransport(_handler_13f('"v2"', calls)))
    again = ih.refresh_institutional_holders(db, client2)
    assert again["status"] == "ok"
    assert any(m == "GET" and "form13f.zip" in u for m, u in calls)
    zip_url = [u for m, u in calls if "jun2026" in u and m == "GET"][0]
    assert _estado(db, zip_url).etag == '"v2"'


def test_head_sin_etag_no_bloquea_el_salto():
    calls = []
    db = tih._db()
    client = httpx.Client(transport=httpx.MockTransport(_handler_13f('"v1"', calls)))
    assert ih.refresh_institutional_holders(db, client)["status"] == "ok"

    calls.clear()
    # HEAD falla: se conserva el salto por URL+procesado.
    client2 = httpx.Client(transport=httpx.MockTransport(_handler_13f('"v2"', calls, fail_head=True)))
    assert ih.refresh_institutional_holders(db, client2)["status"] == "sin_cambios"
    assert not any(m == "GET" and "form13f.zip" in u for m, u in calls)


def test_nport_guarda_etag_y_recalcula_si_cambia():
    from tests import test_fund_holders as tfh

    html = ('<a href="/files/dera/data/form-n-port-data-sets/2026q2_nport.zip">a</a>'
            '<a href="/files/dera/data/form-n-port-data-sets/2026q3_nport.zip">b</a>')
    body = tfh._zip().getvalue()
    calls = []

    def handler(etag):
        def h(request):
            calls.append((request.method, str(request.url)))
            if str(request.url) == fh.nport.DATASETS_PAGE:
                return httpx.Response(200, text=html)
            if request.method == "HEAD":
                return httpx.Response(200, headers={"etag": etag})
            return httpx.Response(200, content=body, headers={"etag": etag})
        return h

    db = tfh._db()
    assert fh.refresh_fund_holders(db, httpx.Client(transport=httpx.MockTransport(handler('"v1"'))))["status"] == "ok"
    state = db.scalars(select(ConnectorState).where(ConnectorState.connector == "form_nport_dataset")).one()
    assert state.etag == '"v1"'

    calls.clear()
    assert fh.refresh_fund_holders(db, httpx.Client(transport=httpx.MockTransport(handler('"v1"'))))["status"] == "sin_cambios"
    assert not any(m == "GET" and "nport.zip" in u for m, u in calls)

    assert fh.refresh_fund_holders(db, httpx.Client(transport=httpx.MockTransport(handler('"v2"'))))["status"] == "ok"
