"""Radar deep value: el screener de Yahoo no se repite en cada vista.

Cada carga del radar hacia la sesion crumb de Yahoo (2 peticiones) y el POST
del screener. Ahora la respuesta se reutiliza 10 min por query; un fallo no
se cachea y "generado en" es la hora real de la consulta a Yahoo.
"""

import pytest

from app.services import yahoo_radar_service as radar

PAYLOAD = {"finance": {"result": [{"quotes": [{"symbol": "AAA", "priceToBook": 0.5}]}]}}


@pytest.fixture(autouse=True)
def _clean():
    getattr(radar, "_screener_cache", {}).clear()
    yield
    getattr(radar, "_screener_cache", {}).clear()


def _counting(monkeypatch, responses):
    calls: list[dict] = []

    def fake_post(query):
        calls.append(query)
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(radar, "_post_screener", fake_post, raising=False)
    return calls


def test_same_query_hits_yahoo_once(monkeypatch):
    calls = _counting(monkeypatch, [PAYLOAD, PAYLOAD])
    query = radar.build_screener_query(yield_min=0, regions=["us"], size=50)
    first = radar.fetch_screener(query)
    second = radar.fetch_screener(dict(query))
    assert len(calls) == 1
    assert first is second
    assert first["finance"] == PAYLOAD["finance"]
    other = radar.build_screener_query(yield_min=0, regions=["es"], size=50)
    radar.fetch_screener(other)
    assert len(calls) == 2


def test_failure_is_not_cached(monkeypatch):
    calls = _counting(monkeypatch, [RuntimeError("yahoo caido"), PAYLOAD])
    query = radar.build_screener_query(yield_min=0, regions=["us"], size=50)
    with pytest.raises(RuntimeError):
        radar.fetch_screener(query)
    assert radar.fetch_screener(query)["finance"] == PAYLOAD["finance"]
    assert len(calls) == 2


def test_generado_en_is_the_yahoo_fetch_time(monkeypatch):
    payload = {**PAYLOAD, "_fetched_at": "2026-10-30T02:00:00+00:00"}

    class _Db:
        def scalars(self, _stmt):
            class _R:
                def all(self):
                    return []

            return _R()

    _, generado_en, _ = radar.run_radar(_Db(), fetcher=lambda q: payload)
    assert generado_en == "2026-10-30T02:00:00+00:00"
