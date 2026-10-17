"""Regression tests: transient worker errors must reach Dramatiq for retry.

Bug-hunt finding: every actor swallowed all exceptions into a `_failure`
payload, which made `max_retries`/`min_backoff` dead — transient errors
(DB blips, Redis drops, upstream 5xx/429) never retried.
"""

import httpx
import pytest
import redis.exceptions as redis_exc
from sqlalchemy import exc as sa_exc

import app.workers.dramatiq_app as workers_module
from app.workers.dramatiq_app import _handle_actor_error, _is_transient


def _http_status_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://upstream.example/api")
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError("boom", request=request, response=response)


@pytest.mark.parametrize(
    "exc",
    [
        ConnectionError("db down"),
        TimeoutError("slow"),
        sa_exc.OperationalError("SELECT 1", {}, Exception("reset")),
        sa_exc.TimeoutError(),
        redis_exc.ConnectionError("redis gone"),
        redis_exc.TimeoutError("redis slow"),
        httpx.ConnectTimeout("upstream slow"),
        httpx.ReadTimeout("upstream slow"),
        httpx.RemoteProtocolError("dropped"),
        _http_status_error(429),
        _http_status_error(503),
    ],
)
def test_transient_errors_are_classified_as_retryable(exc):
    assert _is_transient(exc) is True


@pytest.mark.parametrize(
    "exc",
    [
        ValueError("Document 42 was not found"),
        KeyError("missing_field"),
        TypeError("bad payload"),
        _http_status_error(400),
        _http_status_error(404),
    ],
)
def test_permanent_errors_are_not_retried(exc):
    assert _is_transient(exc) is False


def test_handler_reraises_transient_so_dramatiq_retries():
    with pytest.raises(ConnectionError):
        _handle_actor_error("some_actor", ConnectionError("db down"), ticker="MSFT")


def test_handler_returns_structured_payload_for_permanent_errors():
    result = _handle_actor_error("some_actor", ValueError("not found"), ticker="MSFT")
    assert result["status"] == "error"
    assert result["actor"] == "some_actor"
    assert result["error"]["type"] == "ValueError"
    assert result["error"]["context"] == {"ticker": "MSFT"}


def _sec_error(status_code: int) -> httpx.HTTPStatusError:
    url = "https://www.sec.gov/Archives/edgar/data/320193/x.htm"
    request = httpx.Request("GET", url)
    response = httpx.Response(status_code, request=request)
    # Mensaje con el formato real de httpx (incluye la URL); la atribucion
    # usa el host de la request, no el texto.
    kind = "Client" if status_code < 500 else "Server"
    return httpx.HTTPStatusError(f"{kind} error '{status_code}' for url '{url}'", request=request, response=response)


class _FakeRedis:
    """Redis minimo en memoria con TTL y reloj controlable para el breaker."""

    def __init__(self) -> None:
        self._data: dict[str, tuple[str, float | None]] = {}
        self.now = 0.0

    def _purge(self, key: str) -> None:
        entry = self._data.get(key)
        if entry and entry[1] is not None and self.now >= entry[1]:
            del self._data[key]

    def get(self, key: str):
        self._purge(key)
        entry = self._data.get(key)
        return entry[0] if entry else None

    def incr(self, key: str) -> int:
        self._purge(key)
        value, exp = self._data.get(key, ("0", None))
        value = str(int(value) + 1)
        self._data[key] = (value, exp)
        return int(value)

    def expire(self, key: str, seconds: int) -> None:
        if key in self._data:
            self._data[key] = (self._data[key][0], self.now + seconds)

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._data[key] = (value, self.now + ex if ex is not None else None)

    def delete(self, key: str) -> None:
        self._data.pop(key, None)


def test_sec_403_from_oci_blocked_ip_is_permanent():
    """403 de sec.gov = IP de OCI bloqueada: permanente. Semantica real:
    no reintenta y el actor devuelve payload de error estructurado, asi que
    Dramatiq hace ACK del mensaje (NO va a DLQ; el fallo queda en el
    resultado del job)."""
    assert _is_transient(_sec_error(403)) is False
    wrapped = RuntimeError(f"SEC fetch failed: {_sec_error(403)}")
    assert _is_transient(wrapped) is False


def _is_transient_with(exc, client):
    original = workers_module._redis_client
    workers_module._redis_client = lambda: client
    try:
        return _is_transient(exc)
    finally:
        workers_module._redis_client = original


def test_sec_429_retries_bounded_until_circuit_breaker_trips():
    """429 de sec.gov NO es bloqueo de IP: rate limit que se reintenta
    de forma acotada; una racha en ventana abre el circuit breaker por
    origen (estado en Redis, compartido entre procesos)."""
    client = _FakeRedis()
    limit = workers_module._SEC_429_STREAK_LIMIT
    for _ in range(limit - 1):
        assert _is_transient_with(_sec_error(429), client) is True
    # La que alcanza el limite abre el breaker: permanente.
    assert _is_transient_with(_sec_error(429), client) is False
    # Abierto durante el cooldown: permanente.
    client.now += 60
    assert _is_transient_with(_sec_error(429), client) is False
    # Tras el cooldown se auto-recupera: vuelve a ser transitorio.
    client.now += workers_module._SEC_429_COOLDOWN_S + 1
    assert _is_transient_with(_sec_error(429), client) is True


def test_sec_429_breaker_state_shared_across_processes():
    """La racha la ve cualquier proceso: dos clientes distintos sobre el
    mismo Redis comparten el contador (un proceso no reinicia la racha)."""
    shared = _FakeRedis()
    limit = workers_module._SEC_429_STREAK_LIMIT
    for _ in range(limit - 1):
        assert _is_transient_with(_sec_error(429), shared) is True
    # "Otro proceso" (otra conexion) empuja la racha al limite.
    assert _is_transient_with(_sec_error(429), shared) is False


def test_sec_429_fail_open_when_redis_unavailable():
    """Redis caido -> fail-open (transitorio): con Redis caido el broker
    tampoco consume, y max_retries del actor acota el reintento."""
    class _DownRedis:
        def get(self, key):
            raise ConnectionError("redis down")

    assert _is_transient_with(_sec_error(429), _DownRedis()) is True
    assert _is_transient_with(_sec_error(429), None) is True


def _http_error_for_url(status_code: int, url: str) -> httpx.HTTPStatusError:
    """Error httpx real: mensaje con el formato nativo (incluye la URL) y
    atributos request/response, como el que lanza response.raise_for_status()."""
    request = httpx.Request("GET", url)
    response = httpx.Response(status_code, request=request)
    kind = "Client" if status_code < 500 else "Server"
    reason = "Too Many Requests" if status_code == 429 else "Forbidden"
    return httpx.HTTPStatusError(
        f"{kind} error '{status_code} {reason}' for url '{url}'",
        request=request,
        response=response,
    )


def test_sec_substring_lookalike_domain_is_not_sec():
    """sec.gov.evil.com o notsec.gov NO cuentan como SEC: el host se toma de
    la request real, no de un substring. Un 429 lookalike sigue la via
    generica (transitorio, sin breaker); un 403 lookalike, generico
    permanente (no por politica SEC)."""
    evil_429 = _http_error_for_url(429, "https://sec.gov.evil.example/x")
    # El mensaje nativo de httpx incluye la URL completa, asi que el host
    # lookalike esta presente como texto: el chequeo por substring inseguro
    # lo hubiera marcado SEC; el estructurado no (host exacto o .sec.gov).
    assert evil_429.request.url.host == "sec.gov.evil.example"
    client = _FakeRedis()
    assert _is_transient_with(evil_429, client) is True
    assert client.get(workers_module._SEC_BREAKER_STREAK_KEY) is None
    evil_403 = _http_error_for_url(403, "https://sec.gov.evil.example/x")
    assert _is_transient_with(evil_403, client) is False
    assert client.get(workers_module._SEC_BREAKER_STREAK_KEY) is None


def test_sec_attribution_via_cause_chain():
    """El connector envuelve con `raise RuntimeError(...) from e`: la
    atribucion recorre __cause__ hasta la request httpx real."""
    cause = _http_error_for_url(429, "https://www.sec.gov/Archives/edgar/data/320193/x.htm")
    try:
        try:
            raise cause
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"SEC fetch failed: {e}") from e
    except RuntimeError as wrapped:
        client = _FakeRedis()
        assert _is_transient_with(wrapped, client) is True
        # Si alimento la racha del breaker: es via SEC, no generica.
        assert client.get(workers_module._SEC_BREAKER_STREAK_KEY) == "1"


def test_other_provider_error_mentioning_sec_url_is_not_sec():
    """Un 429 de otro proveedor cuya request NO es sec.gov no alimenta el
    breaker aunque el texto mencione una URL de la SEC."""
    request = httpx.Request("GET", "https://finnhub.io/api/v1/quote")
    response = httpx.Response(429, request=request)
    exc = httpx.HTTPStatusError(
        "Client error '429 Too Many Requests' for url 'https://finnhub.io/api/v1/quote'; "
        "see https://www.sec.gov/Archives for reference",
        request=request,
        response=response,
    )
    client = _FakeRedis()
    assert _is_transient_with(exc, client) is True
    assert client.get(workers_module._SEC_BREAKER_STREAK_KEY) is None
