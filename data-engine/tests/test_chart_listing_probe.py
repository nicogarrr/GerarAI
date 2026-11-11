"""chart_listing_probe: una serie vacía NO es un listado vivo.

Caso real (carril Canadá, 11-nov-2026): SES.TO (Secure Energy Services,
adquirida por GFL el 1-sep-2026) sigue devolviendo 200 con meta en la chart
API de Yahoo — con el último precio congelado — pero CERO barras en 5 días
y en 1 mes. La sonda solo miraba que hubiera ``result`` con ``meta`` y
declaraba «existe»: un listado suspendido pasaba el alta en watchlist como
si cotizara, contradiciendo el propio contrato de la función («serie vacía
= (False, None)»).
"""

from __future__ import annotations

import app.services.connectors.yahoo as yahoo


class _Resp:
    def __init__(self, status=200, payload=None, bad_json=False):
        self.status_code = status
        self._payload = payload
        self._bad = bad_json

    def json(self):
        if self._bad:
            raise ValueError("no json")
        return self._payload


def _meta_payload(timestamps):
    result = {"meta": {"longName": "Suspendida SA", "currency": "CAD"}}
    if timestamps is not None:
        result["timestamp"] = timestamps
    return {"chart": {"result": [result]}}


def _patch(monkeypatch, resp):
    monkeypatch.setattr(yahoo.httpx, "get", lambda *a, **k: resp)


def test_serie_vacia_es_no_existe_aunque_haya_meta(monkeypatch):
    # El caso SES.TO: 200, meta con el último precio congelado, 0 barras.
    _patch(monkeypatch, _Resp(payload=_meta_payload([])))
    assert yahoo.chart_listing_probe("SES.TO", timeout=1.0) == (False, None)


def test_sin_campo_timestamp_es_no_existe(monkeypatch):
    _patch(monkeypatch, _Resp(payload=_meta_payload(None)))
    assert yahoo.chart_listing_probe("SES.TO", timeout=1.0) == (False, None)


def test_listado_vivo_con_barras(monkeypatch):
    _patch(monkeypatch, _Resp(payload=_meta_payload([1784295000, 1784381400])))
    existe, name = yahoo.chart_listing_probe("VIVO.TO", timeout=1.0)
    assert existe is True
    assert name == "Suspendida SA"


def test_404_es_no_existe_y_errores_son_sin_respuesta(monkeypatch):
    _patch(monkeypatch, _Resp(status=404))
    assert yahoo.chart_listing_probe("X", timeout=1.0) == (False, None)
    _patch(monkeypatch, _Resp(status=429))
    assert yahoo.chart_listing_probe("X", timeout=1.0) == (None, None)
    _patch(monkeypatch, _Resp(payload=None, bad_json=True))
    assert yahoo.chart_listing_probe("X", timeout=1.0) == (None, None)
