"""alpha_vantage: bordes de parseo, presupuesto degradado, caché Redis y
mensajes de error del proveedor.

Siguiendo el patrón de test_alpha_vantage_budget_cache.py: red doblada a
nivel httpx.AsyncClient.get (nunca sale a la red), limiter con
min_interval=0 (sin reloj real) y presupuesto con Redis inyectado.

Cubierto aqui:
- _parse_av_float: None, huecos ("None"/""/"abc") y NaN/Infinity -> None
  (NaN/Infinity parsean como float pero no son dato).
- AlphaVantageDailyBudget: limit <= 0 -> ValueError; reserve/used_today/
  mark_exhausted con Redis roto -> degradación a memoria sin inventar cuota;
  used_today leyendo el contador desde Redis.
- Caché con Redis doblado: _cache_set + _cache_get hit entre dos instancias,
  lectura que falla -> None (fail-open), escritura que falla -> no rompe.
- _fetch_network: "Note" por minuto, "Information" sin "per day" y
  "Error Message" -> RuntimeError/ValueError exactos (sin tocar la rama de
  cuota diaria, ya cubierta en test_alpha_vantage_budget_cache.py).
- quote sin "Global Quote" -> RuntimeError; overview sin "Symbol" ->
  RuntimeError; overview con símbolo distinto -> rechazo (nunca otra empresa).
- get_alpha_vantage_client: singleton de proceso (misma instancia, una
  creación), con el global reseteado antes y después de cada test.

Dobles declarados: httpx.AsyncClient.get (red), registry de salud de fuentes
(espía en memoria: es estado global de proceso) y clientes Redis falsos.
app.core.cache._redis_client se dobla a None por defecto en TODOS los tests
(fail-open determinista, sin depender del entorno). El limiter va con
min_interval=0 para no esperar entre llamadas; la expiración de la caché
usa time.monotonic real (los tests no dependen de esperas ni de reloj
doblado). No se prueba la carrera de hilos del singleton ni el SDK real de
Redis/Langfuse.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

import app.services.connectors.alpha_vantage as av_mod
from app.services.connectors.alpha_vantage import (
    AlphaVantageClient,
    AlphaVantageDailyBudget,
    AlphaVantageRateLimiter,
    _parse_av_float,
    get_alpha_vantage_client,
)


@pytest.fixture(autouse=True)
def _sin_redis_ni_estado_global(monkeypatch):
    # Caché fail-open determinista: sin Redis salvo doble explícito del test.
    monkeypatch.setattr("app.core.cache._redis_client", lambda: None)
    # El singleton de proceso no se fuga entre tests y se RESTAURA el valor
    # previo al deshacer el monkeypatch (no se destruye asignando None).
    monkeypatch.setattr(av_mod, "_default_client", None)


class _RegistryEspia:
    """Doble del registry global de salud: registra (motivo) en memoria."""

    def __init__(self) -> None:
        self.failures: list[str] = []
        self.successes: int = 0

    def record_failure(self, name: str, reason: str) -> None:
        self.failures.append(reason)

    def record_success(self, name: str, ms: float) -> None:
        self.successes += 1


def _client(limit: int = 25) -> AlphaVantageClient:
    """Cliente hermético: sin Redis, sin esperas de tasa."""
    budget = AlphaVantageDailyBudget(limit=limit, redis_client_fn=lambda: None)
    return AlphaVantageClient(
        api_key="TEST_KEY",
        budget=budget,
        rate_limiter=AlphaVantageRateLimiter(min_interval=0),
    )


def _response(payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json = lambda: payload
    resp.raise_for_status = lambda: None
    return resp


@pytest.fixture
def registry_espia(monkeypatch):
    espia = _RegistryEspia()
    monkeypatch.setattr(
        "app.services.connectors.alpha_vantage.get_data_source_registry",
        lambda: espia,
    )
    return espia


def test_parse_av_float_huecos_y_no_finitos():
    assert _parse_av_float(None) is None
    assert _parse_av_float("") is None
    assert _parse_av_float("None") is None
    assert _parse_av_float("abc") is None
    # Parsean como float pero no son un dato: fuera (rama math.isfinite).
    assert _parse_av_float("NaN") is None
    assert _parse_av_float("Infinity") is None
    assert _parse_av_float("-Infinity") is None
    assert _parse_av_float("2.5") == 2.5


def test_budget_limit_no_positivo_rechazado():
    with pytest.raises(ValueError) as excinfo:
        AlphaVantageDailyBudget(limit=0, redis_client_fn=lambda: None)
    assert str(excinfo.value) == "limit debe ser > 0, recibido 0"


class _RedisRoto:
    def eval(self, *args):
        raise RuntimeError("redis roto")

    def get(self, key):
        raise RuntimeError("redis roto")

    def set(self, key, value, ex=None):
        raise RuntimeError("redis roto")


def test_budget_reserve_y_used_today_degradan_a_memoria_si_redis_falla():
    budget = AlphaVantageDailyBudget(limit=1, redis_client_fn=lambda: _RedisRoto())

    assert budget.reserve() is True
    assert budget.reserve() is False
    assert budget.used_today() == 1


def test_budget_used_today_lee_el_contador_de_redis():
    class _RedisConSiete:
        def get(self, key):
            return "7"

    budget = AlphaVantageDailyBudget(limit=25, redis_client_fn=lambda: _RedisConSiete())
    assert budget.used_today() == 7


def test_budget_used_today_redis_sin_clave_cae_a_memoria():
    class _RedisVacio:
        def get(self, key):
            return None

        def eval(self, *args):
            raise RuntimeError("sin eval")

    # raw None: la lectura no rompe y manda el contador local.
    budget = AlphaVantageDailyBudget(limit=25, redis_client_fn=lambda: _RedisVacio())
    assert budget.reserve() is True
    assert budget.used_today() == 1


def test_budget_mark_exhausted_con_redis_roto_mantiene_marca_local():
    budget = AlphaVantageDailyBudget(limit=3, redis_client_fn=lambda: _RedisRoto())

    budget.mark_exhausted()

    assert budget.reserve() is False
    assert budget.used_today() == 3


def test_cache_redis_compartido_entre_instancias(monkeypatch):
    class _RedisCache:
        def __init__(self):
            self.store = {}

        def get(self, key):
            return self.store.get(key)

        def set(self, key, value, ex=None):
            self.store[key] = value

    fake = _RedisCache()
    monkeypatch.setattr("app.core.cache._redis_client", lambda: fake)
    sobre = {"fetched_at": "2026-11-09T00:00:00+00:00", "payload": {"x": 1}}

    escritor = _client()
    escritor._cache_set("k1", sobre, ttl=60)

    # Instancia distinta (memoria vacía): el hit viene de Redis.
    lector = _client()
    assert lector._cache_get("k1") == json.loads(json.dumps(sobre, default=str))


def test_cache_lectura_redis_rota_devuelve_none(monkeypatch):
    class _RedisLecturaRota:
        def get(self, key):
            raise RuntimeError("lectura rota")

    monkeypatch.setattr("app.core.cache._redis_client", lambda: _RedisLecturaRota())
    assert _client()._cache_get("k-inexistente") is None


def test_cache_escritura_redis_rota_no_rompe(monkeypatch):
    class _RedisEscrituraRota:
        def set(self, key, value, ex=None):
            raise RuntimeError("escritura rota")

    monkeypatch.setattr("app.core.cache._redis_client", lambda: _RedisEscrituraRota())
    _client()._cache_set("k2", {"payload": {}}, ttl=60)


def test_cache_memoria_expirada_se_borra_y_cae_a_none():
    client = _client()
    # ttl=0: la entrada ya nace expirada (expira_en <= siguiente monotonic),
    # asi que _cache_get la purga y sigue hacia Redis/None sin reloj doblado.
    client._cache_set("k-exp", {"fetched_at": "t", "payload": {}}, ttl=0)

    assert client._cache_get("k-exp") is None
    assert "k-exp" not in client._mem_cache


def test_cache_redis_sin_clave_y_sobre_sin_payload(monkeypatch):
    class _RedisParcial:
        def __init__(self):
            self.store = {"cavaai:alpha-vantage:cache:k-mal": json.dumps({"foo": 1})}

        def get(self, key):
            return self.store.get(key)

    monkeypatch.setattr("app.core.cache._redis_client", lambda: _RedisParcial())
    client = _client()

    # Clave ausente en Redis (raw None) y sobre sin "payload": ambos -> None.
    assert client._cache_get("k-ausente") is None
    assert client._cache_get("k-mal") is None


@pytest.mark.anyio
async def test_fetch_note_por_minuto_es_runtime_error(registry_espia):
    client = _client()
    nota = "Thank you for using Alpha Vantage! 5 API calls per minute allowed."

    async def fake_get(self, url, params=None):
        return _response({"Note": nota})

    with patch("httpx.AsyncClient.get", new=fake_get):
        with pytest.raises(RuntimeError) as excinfo:
            await client.quote("AAPL")

    assert str(excinfo.value) == f"Alpha Vantage rate limit reached: {nota}"
    assert registry_espia.failures == ["rate limit por minuto"]


@pytest.mark.anyio
async def test_fetch_information_sin_per_day_es_runtime_error(registry_espia):
    client = _client()
    info = "Frequency limit: 5 calls per minute for this endpoint."

    async def fake_get(self, url, params=None):
        return _response({"Information": info})

    with patch("httpx.AsyncClient.get", new=fake_get):
        with pytest.raises(RuntimeError) as excinfo:
            await client.quote("AAPL")

    assert str(excinfo.value) == f"Alpha Vantage rate limit reached: {info}"
    assert registry_espia.failures == ["rate limit por minuto"]


@pytest.mark.anyio
async def test_fetch_error_message_es_value_error(registry_espia):
    client = _client()

    async def fake_get(self, url, params=None):
        return _response({"Error Message": "invalid symbol"})

    with patch("httpx.AsyncClient.get", new=fake_get):
        with pytest.raises(ValueError) as excinfo:
            await client.quote("AAPL")

    assert str(excinfo.value) == "Alpha Vantage error: invalid symbol"


@pytest.mark.anyio
async def test_quote_sin_global_quote(registry_espia):
    client = _client()

    async def fake_get(self, url, params=None):
        return _response({})

    with patch("httpx.AsyncClient.get", new=fake_get):
        with pytest.raises(RuntimeError) as excinfo:
            await client.quote("AAPL")

    assert str(excinfo.value) == "Alpha Vantage no devolvió cotización para AAPL"


@pytest.mark.anyio
async def test_overview_sin_symbol(registry_espia):
    client = _client()

    async def fake_get(self, url, params=None):
        return _response({"Name": "Sin símbolo"})

    with patch("httpx.AsyncClient.get", new=fake_get):
        with pytest.raises(RuntimeError) as excinfo:
            await client.overview("AAPL")

    assert str(excinfo.value) == (
        "Alpha Vantage no devolvió datos fundamentales para AAPL"
    )


@pytest.mark.anyio
async def test_overview_symbol_distinto_rechazado(registry_espia):
    client = _client()

    async def fake_get(self, url, params=None):
        return _response({"Symbol": "OTRA", "Name": "Otra empresa"})

    with patch("httpx.AsyncClient.get", new=fake_get):
        with pytest.raises(RuntimeError) as excinfo:
            await client.overview("SAN.MC")

    mensaje = str(excinfo.value)
    assert "'OTRA'" in mensaje and "'SAN.MC'" in mensaje
    assert "respuesta rechazada para no servir otra empresa" in mensaje


@pytest.mark.anyio
async def test_fetch_data_no_dict_cuenta_exito_y_falla_en_quote(registry_espia):
    client = _client()

    async def fake_get(self, url, params=None):
        return _response(["no", "es", "dict"])

    with patch("httpx.AsyncClient.get", new=fake_get):
        with pytest.raises(RuntimeError) as excinfo:
            await client.quote("AAPL")

    # data no es dict: se salta el chequeo de avisos, cuenta exito y devuelve
    # {} (rama isinstance False); quote entonces no encuentra "Global Quote".
    assert registry_espia.successes == 1
    assert str(excinfo.value) == "Alpha Vantage no devolvió cotización para AAPL"


def test_get_alpha_vantage_client_es_singleton():
    primero = get_alpha_vantage_client()
    segundo = get_alpha_vantage_client()

    assert primero is segundo
    assert av_mod._default_client is primero
