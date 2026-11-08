"""Huecos de cobertura en market (lote 16).

Medicion previa (mismo metodo, tests que referencian el modulo): market 37,8 %.
Se cubren: _fetch_index (no-200, excepciones), el cliente Yahoo compartido
(crear/reusar/cerrar), _bar_in_open_session, _fetch_yahoo_quote (todas sus
ramas: vela colgante rellenada con regularMarketPrice, barra de sesion en
curso descartada, sin cierres, cierre cero, cierre previo invalido, zona
mala, timestamp ausente, payload malformado), /quote (404 por simbolo malo,
cache, cache llena, sin dato), helpers del batch (redis key, cliente redis
best-effort, normalizacion), /quotes/batch (400 por lote grande, vacio, L1
memoria, L2 Redis, fallo de lectura fail-open, misses con fetch, escritura
Redis fallida), _fetch_yahoo_candles (errores, optional_value, huecos, sin
cierres, divisa, malformado), /candles (404, cache, cache llena, sin dato),
/indices (fetch con pool y cache), _compute_themes_payload y /themes.

Que NO se prueba aqui: nada de HTTP ni auth; NINGUNA llamada de red real a
Yahoo (los clientes httpx son falsos o el fetch va doblado); Redis es un
doble en memoria; market_themes.fetch_all/compute_themes van doblados (solo
delegacion); el ThreadPoolExecutor ejecuta funciones dobladas; el reloj se
dobla donde hace falta fijar la sesion. La base de datos no interviene en
estas rutas.
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from fastapi import HTTPException

from app.api.routes import market as m


@pytest.fixture(autouse=True)
def _caches_limpias():
    # Limpia ANTES y DESPUES: el ultimo test del archivo no puede dejar caches
    # falsas que contaminen otros archivos de la suite (orden de pytest).
    m._quote_cache.clear()
    m._candles_cache.clear()
    m._cache.update({"at": 0.0, "items": [], "fetched_at": None})
    yield
    m._quote_cache.clear()
    m._candles_cache.clear()
    m._cache.update({"at": 0.0, "items": [], "fetched_at": None})
    m.close_shared_yahoo_client()


class _ClienteFalso:
    def __init__(self, *a, **kw):
        self.params = {}
        self.is_closed = False

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.is_closed = True
        return False

    def close(self):
        self.is_closed = True


def _resp_yahoo(closes, timestamps=None, meta=None, status=200, extras=None):
    quote = {"close": closes}
    if extras:
        quote.update(extras)
    return SimpleNamespace(
        status_code=status,
        json=lambda: {
            "chart": {
                "result": [{
                    "indicators": {"quote": [quote]},
                    "timestamp": timestamps or [],
                    "meta": meta or {},
                }]
            }
        },
    )


# --- _fetch_index ------------------------------------------------------------------


def test_fetch_index_no_200():
    cliente = Mock()
    cliente.get.return_value = SimpleNamespace(status_code=503)
    assert m._fetch_index(cliente, "^GSPC") is None


def test_fetch_index_error_http():
    cliente = Mock()
    cliente.get.side_effect = httpx.HTTPError("red caida")
    assert m._fetch_index(cliente, "^GSPC") is None


def test_fetch_index_payload_malformado():
    cliente = Mock()
    cliente.get.return_value = SimpleNamespace(status_code=200, json=lambda: {"chart": {}})
    assert m._fetch_index(cliente, "^GSPC") is None


# --- cliente compartido --------------------------------------------------------------


def test_cliente_compartido_crea_reusa_y_cierra(monkeypatch):
    creados = []
    monkeypatch.setattr(m.httpx, "Client", lambda *a, **kw: creados.append(1) or _ClienteFalso())
    m._yahoo_client = None
    primero = m._shared_yahoo_client()
    assert m._shared_yahoo_client() is primero
    assert len(creados) == 1
    m.close_shared_yahoo_client()
    assert m._yahoo_client is None
    # Tras cerrar, el siguiente lo recrea.
    segundo = m._shared_yahoo_client()
    assert len(creados) == 2
    m.close_shared_yahoo_client()


# --- _bar_in_open_session -------------------------------------------------------------


def test_barra_en_sesion_abierta():
    meta = {"currentTradingPeriod": {"regular": {"start": 100, "end": 200}}}
    assert m._bar_in_open_session(meta, 150, now_ts=160) is True
    # Barra anterior a la apertura: no es la sesion en curso.
    assert m._bar_in_open_session(meta, 50, now_ts=160) is False
    # Sesion ya cerrada.
    assert m._bar_in_open_session(meta, 150, now_ts=250) is False
    # Tipos incompletos: False, nunca se inventa.
    assert m._bar_in_open_session({}, None, now_ts=160) is False


# --- _fetch_yahoo_quote -----------------------------------------------------------------


def test_quote_error_http():
    cliente = Mock()
    cliente.get.side_effect = httpx.HTTPError("red caida")
    assert m._fetch_yahoo_quote(cliente, "SAN.MC") is None


def test_quote_no_200():
    cliente = Mock()
    cliente.get.return_value = SimpleNamespace(status_code=404)
    assert m._fetch_yahoo_quote(cliente, "SAN.MC") is None


def test_quote_feliz():
    cliente = Mock()
    cliente.get.return_value = _resp_yahoo(
        [10.0, 12.0],
        timestamps=[1_700_000_000, 1_700_086_400],
        meta={"currency": "EUR", "exchangeTimezoneName": "Europe/Madrid"},
        extras={"open": [9.5, 11.0], "high": [10.5, 12.5], "low": [9.0, 11.5]},
    )
    result = m._fetch_yahoo_quote(cliente, "SAN.MC")
    assert result["c"] == 12.0
    assert result["d"] == 2.0
    assert result["dp"] == pytest.approx(20.0)
    assert result["pc"] == 10.0
    assert result["o"] == 11.0
    assert result["h"] == 12.5
    assert result["l"] == 11.5
    assert result["ct"] == 1_700_086_400
    assert result["cd"] is not None
    assert result["currency"] == "EUR"


def test_quote_vela_colgante_se_rellena_con_cierre_regular():
    # Ultima vela en None pero regularMarketTime ya paso el fin de sesion:
    # la vela se da por cerrada con regularMarketPrice.
    meta = {
        "currentTradingPeriod": {"regular": {"start": 1_700_086_400 - 100, "end": 1_700_086_400}},
        "regularMarketTime": 1_700_086_500,
        "regularMarketPrice": 347.1,
    }
    cliente = Mock()
    cliente.get.return_value = _resp_yahoo(
        [340.0, None], timestamps=[1_700_000_000, 1_700_086_400 - 50], meta=meta
    )
    # Ajuste: el sello de la vela debe caer dentro de la sesion.
    cliente.get.return_value = _resp_yahoo(
        [340.0, None], timestamps=[1_700_000_000, 1_700_086_350], meta=meta
    )
    result = m._fetch_yahoo_quote(cliente, "AAPL")
    assert result["c"] == 347.1


def test_quote_barra_de_sesion_en_curso_se_descarta(monkeypatch):
    # La ultima barra pertenece a la sesion abierta: no es un cierre oficial.
    ahora = 1_700_090_000
    meta = {
        "currentTradingPeriod": {"regular": {"start": ahora - 3_000, "end": ahora + 3_000}},
        "exchangeTimezoneName": "America/New_York",
    }
    monkeypatch.setattr(m.time, "time", lambda: ahora)
    cliente = Mock()
    cliente.get.return_value = _resp_yahoo(
        [10.0, 12.0], timestamps=[ahora - 90_000, ahora - 100], meta=meta
    )
    result = m._fetch_yahoo_quote(cliente, "CGEO.L")
    assert result["c"] == 10.0
    assert result["pc"] is None


def test_quote_todas_las_velas_colgantes_es_none():
    cliente = Mock()
    cliente.get.return_value = _resp_yahoo([None, None], timestamps=[1, 2])
    assert m._fetch_yahoo_quote(cliente, "X") is None


def test_quote_cierre_cero_es_none():
    cliente = Mock()
    cliente.get.return_value = _resp_yahoo([0.0], timestamps=[1])
    assert m._fetch_yahoo_quote(cliente, "X") is None


def test_quote_cierre_previo_no_positivo_queda_none():
    cliente = Mock()
    cliente.get.return_value = _resp_yahoo([0.0, 12.0], timestamps=[1, 2])
    result = m._fetch_yahoo_quote(cliente, "X")
    assert result["pc"] is None
    assert result["d"] is None
    assert result["dp"] is None


def test_quote_un_cierre_sin_previo_valido():
    cliente = Mock()
    cliente.get.return_value = _resp_yahoo(
        [12.0], timestamps=[2], meta={"chartPreviousClose": "no-numero"}
    )
    result = m._fetch_yahoo_quote(cliente, "X")
    assert result["c"] == 12.0
    assert result["pc"] is None


def test_quote_sin_timestamps_fecha_none():
    cliente = Mock()
    cliente.get.return_value = _resp_yahoo([10.0, 12.0], timestamps=[])
    result = m._fetch_yahoo_quote(cliente, "X")
    assert result["ct"] is None
    assert result["cd"] is None


def test_quote_zona_invalida_fecha_none():
    cliente = Mock()
    cliente.get.return_value = _resp_yahoo(
        [10.0, 12.0], timestamps=[1, 2], meta={"exchangeTimezoneName": "No/Existe"}
    )
    result = m._fetch_yahoo_quote(cliente, "X")
    assert result["ct"] == 2
    assert result["cd"] is None


def test_quote_payload_malformado():
    cliente = Mock()
    cliente.get.return_value = SimpleNamespace(status_code=200, json=lambda: {"chart": {}})
    assert m._fetch_yahoo_quote(cliente, "X") is None


# --- /quote ----------------------------------------------------------------------------


def test_market_quote_simbolo_malo_es_404():
    with pytest.raises(HTTPException) as exc:
        m.market_quote("A" * 40)
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException):
        m.market_quote("AA\x00BB")


def test_market_quote_feliz_y_cache(monkeypatch):
    llamadas = []
    monkeypatch.setattr(m, "_shared_yahoo_client", lambda: Mock())
    monkeypatch.setattr(
        m,
        "_fetch_yahoo_quote",
        lambda client, symbol: llamadas.append(symbol) or {"c": 1.0},
    )
    assert m.market_quote("san.mc") == {"c": 1.0}
    assert m.market_quote("SAN.MC") == {"c": 1.0}
    assert llamadas == ["SAN.MC"]


def test_market_quote_sin_dato_es_404(monkeypatch):
    monkeypatch.setattr(m, "_shared_yahoo_client", lambda: Mock())
    monkeypatch.setattr(m, "_fetch_yahoo_quote", lambda client, symbol: None)
    with pytest.raises(HTTPException) as exc:
        m.market_quote("SAN.MC")
    assert exc.value.status_code == 404


def test_market_quote_cache_llena_se_vacia(monkeypatch):
    ahora = time.monotonic()
    for i in range(m._QUOTE_CACHE_MAX):
        m._quote_cache[f"X{i}"] = {"at": ahora, "data": {}}
    monkeypatch.setattr(m, "_shared_yahoo_client", lambda: Mock())
    monkeypatch.setattr(m, "_fetch_yahoo_quote", lambda client, symbol: {"c": 2.0})
    assert m.market_quote("NUEVA") == {"c": 2.0}
    assert len(m._quote_cache) == 1


# --- helpers del batch ------------------------------------------------------------------


def test_quote_redis_key():
    assert m._quote_redis_key("SAN.MC") == "cavaai:market:quote:SAN.MC"


def test_batch_redis_client_best_effort(monkeypatch):
    from app.core import cache

    monkeypatch.setattr(cache, "_redis_client", lambda: "cliente-redis")
    assert m._batch_redis_client() == "cliente-redis"

    def roto():
        raise ConnectionError("redis caido")

    monkeypatch.setattr(cache, "_redis_client", roto)
    assert m._batch_redis_client() is None


def test_normaliza_simbolos_del_batch():
    assert m._normalize_batch_symbols(
        ["san.mc", "SAN.MC", " ", "A" * 40, "BB\x00AA", "rep"]
    ) == ["SAN.MC", "REP"]


class _RedisFalso:
    def __init__(self, datos=None, falla_leer=False, falla_escribir=False):
        self._datos = datos or {}
        self._falla_leer = falla_leer
        self._falla_escribir = falla_escribir
        self.escritos = {}

    def get(self, key):
        if self._falla_leer:
            raise ConnectionError("lectura rota")
        return self._datos.get(key)

    def set(self, key, value, ex=None):
        if self._falla_escribir:
            raise ConnectionError("escritura rota")
        self.escritos[key] = value


# --- /quotes/batch ----------------------------------------------------------------------


def test_batch_demasiado_grande_es_400():
    body = m.MarketQuotesBatchIn(symbols=["X"] * (m._QUOTES_BATCH_MAX + 1))
    with pytest.raises(HTTPException) as exc:
        m.market_quotes_batch(body)
    assert exc.value.status_code == 400


def test_batch_vacio_tras_normalizar():
    assert m.market_quotes_batch(m.MarketQuotesBatchIn(symbols=[" ", "??\x00"])) == {"quotes": {}}


def test_batch_l1_memoria_y_l2_redis(monkeypatch):
    ahora = time.monotonic()
    m._quote_cache["EN_MEMORIA"] = {"at": ahora, "data": {"c": 1.0}}
    redis = _RedisFalso({"cavaai:market:quote:EN_REDIS": '{"c": 2.0}'})
    monkeypatch.setattr(m, "_batch_redis_client", lambda: redis)
    body = m.MarketQuotesBatchIn(symbols=["EN_MEMORIA", "EN_REDIS"])
    result = m.market_quotes_batch(body)
    assert result["quotes"] == {"EN_MEMORIA": {"c": 1.0}, "EN_REDIS": {"c": 2.0}}


def test_batch_lectura_redis_rota_fail_open(monkeypatch):
    redis = _RedisFalso(falla_leer=True)
    monkeypatch.setattr(m, "_batch_redis_client", lambda: redis)
    monkeypatch.setattr(m, "_shared_yahoo_client", lambda: Mock())
    monkeypatch.setattr(m, "_fetch_yahoo_quote", lambda client, symbol: {"c": 3.0})
    result = m.market_quotes_batch(m.MarketQuotesBatchIn(symbols=["SAN.MC"]))
    assert result["quotes"] == {"SAN.MC": {"c": 3.0}}
    assert "cavaai:market:quote:SAN.MC" in redis.escritos
    assert m._quote_cache["SAN.MC"]["data"] == {"c": 3.0}


def test_batch_miss_sin_dato_y_escritura_redis_rota(monkeypatch):
    redis = _RedisFalso(falla_escribir=True)
    monkeypatch.setattr(m, "_batch_redis_client", lambda: redis)
    monkeypatch.setattr(m, "_shared_yahoo_client", lambda: Mock())
    monkeypatch.setattr(
        m,
        "_fetch_yahoo_quote",
        lambda client, symbol: {"c": 1.0} if symbol == "CON_DATO" else None,
    )
    result = m.market_quotes_batch(m.MarketQuotesBatchIn(symbols=["CON_DATO", "SIN_DATO"]))
    assert result["quotes"] == {"CON_DATO": {"c": 1.0}, "SIN_DATO": None}
    assert "SIN_DATO" not in m._quote_cache


# --- _fetch_yahoo_candles ------------------------------------------------------------------


def test_candles_error_http():
    cliente = Mock()
    cliente.get.side_effect = httpx.HTTPError("red caida")
    assert m._fetch_yahoo_candles(cliente, "SAN.MC", 0, 10, "1d") is None


def test_candles_no_200():
    cliente = Mock()
    cliente.get.return_value = SimpleNamespace(status_code=404)
    assert m._fetch_yahoo_candles(cliente, "SAN.MC", 0, 10, "1d") is None


def _resp_candles(closes, timestamps, meta=None, **extras):
    quote = {"close": closes}
    quote.update(extras)
    return SimpleNamespace(
        status_code=200,
        json=lambda: {
            "chart": {
                "result": [{
                    "indicators": {"quote": [quote]},
                    "timestamp": timestamps,
                    "meta": meta or {},
                }]
            }
        },
    )


def test_candles_feliz_con_huecos_y_divisa():
    cliente = Mock()
    cliente.get.return_value = _resp_candles(
        [10.0, None, 12.0],
        [100, 200, 300],
        meta={"currency": "EUR"},
        open=[9.0, 11.0],  # mas corto que closes: el indice 2 cae fuera -> None
        high=["malo", 10.5, 12.5],
        low=[9.0, 9.5, 11.5],
        volume=[1000, None, 3000],
    )
    result = m._fetch_yahoo_candles(cliente, "SAN.MC", 0, 400, "1d")
    assert result["s"] == "ok"
    assert result["c"] == [10.0, 12.0]
    assert result["t"] == [100, 300]
    assert result["o"] == [9.0, None]
    assert result["h"] == [None, 12.5]
    assert result["v"] == [1000.0, 3000.0]
    assert result["currency"] == "EUR"


def test_candles_sin_cierres_validos():
    cliente = Mock()
    cliente.get.return_value = _resp_candles([None, None], [1, 2])
    assert m._fetch_yahoo_candles(cliente, "X", 0, 10, "1d") is None


def test_candles_malformado():
    cliente = Mock()
    cliente.get.return_value = SimpleNamespace(status_code=200, json=lambda: {"chart": {}})
    assert m._fetch_yahoo_candles(cliente, "X", 0, 10, "1d") is None


# --- /candles -----------------------------------------------------------------------------


def test_market_candles_params_malos_es_404():
    with pytest.raises(HTTPException) as exc:
        m.market_candles("A" * 40, from_ts=0, to_ts=10)
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException):
        m.market_candles("SAN.MC", from_ts=10, to_ts=10)


def test_market_candles_feliz_y_cache(monkeypatch):
    llamadas = []
    monkeypatch.setattr(m, "_shared_yahoo_client", lambda: Mock())
    monkeypatch.setattr(
        m,
        "_fetch_yahoo_candles",
        lambda client, symbol, f, t, i: llamadas.append(symbol) or {"s": "ok", "c": [1.0]},
    )
    assert m.market_candles("SAN.MC", from_ts=0, to_ts=100_000)["s"] == "ok"
    assert m.market_candles("SAN.MC", from_ts=0, to_ts=100_000)["s"] == "ok"
    assert llamadas == ["SAN.MC"]


def test_market_candles_sin_dato_es_404(monkeypatch):
    monkeypatch.setattr(m, "_shared_yahoo_client", lambda: Mock())
    monkeypatch.setattr(m, "_fetch_yahoo_candles", lambda *a: None)
    with pytest.raises(HTTPException) as exc:
        m.market_candles("SAN.MC", from_ts=0, to_ts=100)
    assert exc.value.status_code == 404


def test_market_candles_cache_llena_se_vacia(monkeypatch):
    ahora = time.monotonic()
    for i in range(m._CANDLES_CACHE_MAX):
        m._candles_cache[("X", "1d", 0, i)] = {"at": ahora, "data": {}}
    monkeypatch.setattr(m, "_shared_yahoo_client", lambda: Mock())
    monkeypatch.setattr(m, "_fetch_yahoo_candles", lambda *a: {"s": "ok"})
    assert m.market_candles("NUEVA", from_ts=0, to_ts=100) == {"s": "ok"}
    assert len(m._candles_cache) == 1


# --- /indices -----------------------------------------------------------------------------


def test_market_indices_fetch_y_cache(monkeypatch):
    monkeypatch.setattr(m.httpx, "Client", lambda *a, **kw: _ClienteFalso())
    monkeypatch.setattr(
        m,
        "_fetch_index",
        lambda client, symbol: {
            "symbol": symbol, "priceAsOf": 1, "price": 100.0, "change": 1.0, "changePercent": 1.0,
        },
    )
    primero = m.market_indices()
    assert primero["source"] == "yahoo_finance"
    assert len(primero["indices"]) == len(m._INDEXES)
    assert primero["indices"][0]["price"] == 100.0
    # Segunda llamada: cache caliente, sin refetch.
    monkeypatch.setattr(m, "_fetch_index", lambda *a: pytest.fail("no deberia refetchear"))
    segundo = m.market_indices()
    assert segundo["indices"] == primero["indices"]


# --- themes --------------------------------------------------------------------------------


def test_compute_themes_payload_delega(monkeypatch):
    visto = {}
    monkeypatch.setattr(m.httpx, "Client", lambda *a, **kw: _ClienteFalso())
    monkeypatch.setattr(m.market_themes, "all_symbols", lambda: ["A", "B"])
    monkeypatch.setattr(
        m.market_themes,
        "fetch_all",
        lambda symbols, fetcher: visto.update(symbols=list(symbols)) or {"A": []},
    )
    monkeypatch.setattr(
        m.market_themes,
        "compute_themes",
        lambda candles, generated_at: {"themes": [], "n": len(candles)},
    )
    monkeypatch.setattr(m, "_fetch_yahoo_candles", lambda *a: None)
    result = m._compute_themes_payload()
    assert visto["symbols"] == ["A", "B"]
    assert result == {"themes": [], "n": 1}


def test_market_themes_ranking(monkeypatch):
    monkeypatch.setattr(m, "_compute_themes_payload", lambda: {"themes": [1]})
    monkeypatch.setattr(m, "_themes_cache", SimpleNamespace(get=lambda fn: fn()))
    monkeypatch.setattr(
        m.market_themes, "with_live_intraday", lambda payload: {"live": payload}
    )
    assert m.market_themes_ranking() == {"live": {"themes": [1]}}


# --- ramas finas ----------------------------------------------------------------


def test_batch_sin_redis_fetch_directo_y_cache_llena(monkeypatch):
    # Sin Redis: salta L2 y la escritura; con la cache en memoria llena se
    # vacia antes de escribir el dato nuevo.
    monkeypatch.setattr(m, "_batch_redis_client", lambda: None)
    monkeypatch.setattr(m, "_shared_yahoo_client", lambda: Mock())
    monkeypatch.setattr(m, "_fetch_yahoo_quote", lambda client, symbol: {"c": 1.0})
    ahora = time.monotonic()
    for i in range(m._QUOTE_CACHE_MAX):
        m._quote_cache[f"X{i}"] = {"at": ahora, "data": {}}
    result = m.market_quotes_batch(m.MarketQuotesBatchIn(symbols=["SAN.MC"]))
    assert result["quotes"] == {"SAN.MC": {"c": 1.0}}
    assert len(m._quote_cache) == 1


def test_candles_sin_divisa_en_meta():
    cliente = Mock()
    cliente.get.return_value = _resp_candles([10.0], [100], meta={})
    result = m._fetch_yahoo_candles(cliente, "X", 0, 400, "1d")
    assert "currency" not in result


def test_indices_sin_quotes_universo_vacio(monkeypatch):
    monkeypatch.setattr(m.httpx, "Client", lambda *a, **kw: _ClienteFalso())
    monkeypatch.setattr(m, "_fetch_index", lambda client, symbol: None)
    result = m.market_indices()
    assert result["indices"] == []
