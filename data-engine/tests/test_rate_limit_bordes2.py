"""Bordes de ``app.core.rate_limit``: rutas Redis, enforce auxiliares y middleware.

Lo que cada test demuestra:
- ``_record_hit`` con Redis (fake en ``app.core.redis_client.short_async_redis``):
  pipeline correcto y ``(count, retry_after)`` exactos con reloj fijado (144-159);
  Redis caido con ``degrade_to_local=False`` -> RateLimitBackendUnavailable;
  con ``True`` degrada al contador local (161->167); el local purga hits
  caducados (170-171).
- ``_count_hits`` con Redis devuelve el zcount con la ventana exacta (395-398).
- ``enforce_llm_test_rate_limit``: desactivado no cuenta; bajo limite pasa;
  sobre limite 429 con Retry-After; backend caido 503 (241-272).
- ``enforce_public_ip_rate_limit``: igual con el limite publico (311-338).
- ``AuthFailureLimitMiddleware``: no-http pasa; desactivado/exento/OPTIONS
  pasa; fallo del store no tumba la peticion; sobre limite sin firma valida
  429; un 401 se registra y un fallo al registrar no rompe la respuesta
  (478-527).

Sin red: Redis es un fake en memoria y los tests del middleware usan un
harness ASGI local. El reloj se fija con monkeypatch sobre ``_now``.
"""

from __future__ import annotations

import asyncio
import hashlib
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

import app.core.rate_limit as rl
from app.core.rate_limit import (
    AuthFailureLimitMiddleware,
    RateLimitBackendUnavailable,
    _count_hits,
    _local_hits,
    _record_hit,
    enforce_llm_test_rate_limit,
    enforce_public_ip_rate_limit,
)

_MISSING = object()


def _preserve_key(key):
    """Restaurador del valor previo de una clave: no se pierde estado global."""
    prior = _local_hits.get(key, _MISSING)

    def restore():
        if prior is _MISSING:
            _local_hits.pop(key, None)
        else:
            _local_hits[key] = prior

    return restore


# --- Fakes Redis ------------------------------------------------------------


class _Pipe:
    def __init__(self, result):
        self._result = result
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def zremrangebyscore(self, *a):
        self.calls.append(("zremrangebyscore", a))

    def zadd(self, *a):
        self.calls.append(("zadd", a))

    def zcard(self, *a):
        self.calls.append(("zcard", a))

    def expire(self, *a):
        self.calls.append(("expire", a))

    def zrange(self, *a, **kw):
        self.calls.append(("zrange", a, kw))

    async def execute(self):
        return self._result


class _RedisCM:
    def __init__(self, client):
        self._client = client

    async def __aenter__(self):
        return self._client

    async def __aexit__(self, *a):
        return False


class _Client:
    def __init__(self, pipe=None, zcount_result=0):
        self._pipe = pipe
        self._zcount_result = zcount_result
        self.zcount_args = None

    def pipeline(self, transaction=True):
        return self._pipe

    async def zcount(self, *a):
        self.zcount_args = a
        return self._zcount_result


def _redis_down(url):
    raise OSError("store unreachable")


def _request(client=("9.9.9.9", 1), method="GET", path="/api/feed", headers=()):
    return Request(
        {
            "type": "http",
            "client": client,
            "method": method,
            "path": path,
            "scheme": "http",
            "server": ("test", 80),
            "headers": list(headers),
        }
    )


def _settings(**kw):
    base = dict(
        rate_limit_enabled=True,
        is_local_environment=True,
        is_production=False,
        redis_url="redis://127.0.0.1:6399/15",
        rate_limit_local_request_floor=0,
        forwarded_allow_ips="",
    )
    base.update(kw)
    return SimpleNamespace(**base)


# --- _record_hit ------------------------------------------------------------


def test_record_hit_redis_devuelve_count_y_retry_exactos(monkeypatch):
    monkeypatch.setattr(rl, "_now", lambda: 1000.0)
    pipe = _Pipe([None, None, 3, None, [("m", 950.0)]])
    monkeypatch.setattr("app.core.redis_client.short_async_redis", lambda url: _RedisCM(_Client(pipe)))
    count, retry = asyncio.run(
        _record_hit(
            "k",
            window_seconds=60,
            use_redis=True,
            redis_url="redis://x",
            degrade_to_local=False,
        )
    )
    assert (count, retry) == (3, 10)  # max(1, ceil(950 + 60 - 1000))
    assert pipe.calls[0] == ("zremrangebyscore", ("k", "-inf", 940.0))
    assert pipe.calls[2] == ("zcard", ("k",))
    assert pipe.calls[3] == ("expire", ("k", 65))
    assert pipe.calls[4][0] == "zrange"
    assert pipe.calls[1][0] == "zadd" and pipe.calls[1][1][0] == "k"


def test_record_hit_redis_caido_sin_degradar_lanza(monkeypatch):
    monkeypatch.setattr("app.core.redis_client.short_async_redis", _redis_down)
    with pytest.raises(RateLimitBackendUnavailable, match="rate-limit store unreachable"):
        asyncio.run(
            _record_hit(
                "k",
                window_seconds=60,
                use_redis=True,
                redis_url="redis://x",
                degrade_to_local=False,
            )
        )


def test_record_hit_redis_caido_degrada_a_local(monkeypatch):
    monkeypatch.setattr(rl, "_now", lambda: 1000.0)
    monkeypatch.setattr("app.core.redis_client.short_async_redis", _redis_down)
    key = "bordes2:degrada"
    restore = _preserve_key(key)
    _local_hits.pop(key, None)
    try:
        count, retry = asyncio.run(
            _record_hit(
                key,
                window_seconds=60,
                use_redis=True,
                redis_url="redis://x",
                degrade_to_local=True,
            )
        )
        assert (count, retry) == (1, 60)
    finally:
        restore()


def test_record_hit_local_purga_caducados(monkeypatch):
    monkeypatch.setattr(rl, "_now", lambda: 1000.0)
    key = "bordes2:purga"
    restore = _preserve_key(key)
    from collections import deque

    _local_hits[key] = deque([900.0, 999.0])  # 900 caducado (corte 940)
    try:
        count, retry = asyncio.run(
            _record_hit(
                key,
                window_seconds=60,
                use_redis=False,
                redis_url="",
                degrade_to_local=True,
            )
        )
        assert count == 2  # 999 y el nuevo 1000; el 900 se purga
        assert retry == 59  # max(1, ceil(999 + 60 - 1000))
    finally:
        restore()


def test_count_hits_redis_ventana_exacta(monkeypatch):
    monkeypatch.setattr(rl, "_now", lambda: 1000.0)
    client = _Client(zcount_result=7)
    monkeypatch.setattr("app.core.redis_client.short_async_redis", lambda url: _RedisCM(client))
    n = asyncio.run(_count_hits("k", use_redis=True, redis_url="redis://x"))
    assert n == 7
    assert client.zcount_args == ("k", 940.0, "+inf")


# --- enforce_llm_test_rate_limit --------------------------------------------


def test_llm_test_desactivado_no_cuenta(monkeypatch):
    monkeypatch.setattr(rl, "get_settings", lambda: _settings(rate_limit_enabled=False))
    assert asyncio.run(enforce_llm_test_rate_limit(_request(), None)) is None


def test_llm_test_bajo_limite_pasa(monkeypatch):
    monkeypatch.setattr(rl, "get_settings", lambda: _settings())
    digest = hashlib.sha256(b"anonymous@9.9.9.9:llm-test").hexdigest()
    key = f"cavaai:rate:{digest}"
    restore = _preserve_key(key)
    _local_hits.pop(key, None)
    try:
        assert asyncio.run(enforce_llm_test_rate_limit(_request(), None)) is None
        assert len(_local_hits[key]) == 1
    finally:
        restore()


def test_llm_test_sobre_limite_429(monkeypatch):
    # Entorno no local: el limite no se eleva al suelo local (rama 245->247).
    monkeypatch.setattr(rl, "get_settings", lambda: _settings(is_local_environment=False))

    async def fake_record(*a, **kw):
        return 11, 30

    monkeypatch.setattr(rl, "_record_hit", fake_record)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(enforce_llm_test_rate_limit(_request(), None))
    assert exc.value.status_code == 429
    assert exc.value.detail == "Rate limit exceeded"
    assert exc.value.headers == {"Retry-After": "30"}


def test_llm_test_backend_caido_503(monkeypatch):
    monkeypatch.setattr(rl, "get_settings", lambda: _settings())

    async def fake_record(*a, **kw):
        raise RateLimitBackendUnavailable("rate-limit store unreachable")

    monkeypatch.setattr(rl, "_record_hit", fake_record)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(enforce_llm_test_rate_limit(_request(), None))
    assert exc.value.status_code == 503
    assert exc.value.detail == "Rate limit backend unavailable"


# --- enforce_public_ip_rate_limit -------------------------------------------


def test_public_ip_desactivado_no_cuenta(monkeypatch):
    monkeypatch.setattr(rl, "get_settings", lambda: _settings(rate_limit_enabled=False))
    assert asyncio.run(enforce_public_ip_rate_limit(_request())) is None


def test_public_ip_bajo_limite_pasa(monkeypatch):
    monkeypatch.setattr(rl, "get_settings", lambda: _settings())

    async def fake_record(*a, **kw):
        return 1, 5

    monkeypatch.setattr(rl, "_record_hit", fake_record)
    assert asyncio.run(enforce_public_ip_rate_limit(_request())) is None


def test_public_ip_sobre_limite_429(monkeypatch):
    monkeypatch.setattr(rl, "get_settings", lambda: _settings())

    async def fake_record(*a, **kw):
        return 61, 5

    monkeypatch.setattr(rl, "_record_hit", fake_record)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(enforce_public_ip_rate_limit(_request()))
    assert exc.value.status_code == 429
    assert exc.value.headers == {"Retry-After": "5"}


def test_public_ip_backend_caido_503(monkeypatch):
    monkeypatch.setattr(rl, "get_settings", lambda: _settings())

    async def fake_record(*a, **kw):
        raise RateLimitBackendUnavailable("rate-limit store unreachable")

    monkeypatch.setattr(rl, "_record_hit", fake_record)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(enforce_public_ip_rate_limit(_request()))
    assert exc.value.status_code == 503
    assert exc.value.detail == "Rate limit backend unavailable"


# --- AuthFailureLimitMiddleware ---------------------------------------------


def _scope(**kw):
    base = {
        "type": "http",
        "method": "GET",
        "path": "/private",
        "client": ("8.8.8.8", 1),
        "headers": [],
        "scheme": "http",
        "server": ("test", 80),
    }
    base.update(kw)
    return base


def _app_status(status):
    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": status, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})

    return app


async def _run(mw, scope):
    sent = []

    async def receive():
        return {"type": "http.request", "body": b""}

    async def send(message):
        sent.append(message)

    await mw(scope, receive, send)
    return sent


def test_middleware_no_http_pasa(monkeypatch):
    called = []

    async def app(scope, receive, send):
        called.append(scope["type"])

    mw = AuthFailureLimitMiddleware(app)
    asyncio.run(_run(mw, {"type": "lifespan"}))
    assert called == ["lifespan"]


def test_middleware_desactivado_exento_y_options_pasan(monkeypatch):
    called = []

    async def app(scope, receive, send):
        called.append(scope["path"])

    monkeypatch.setattr(rl, "get_settings", lambda: _settings(rate_limit_enabled=False))
    asyncio.run(_run(AuthFailureLimitMiddleware(app), _scope()))
    monkeypatch.setattr(rl, "get_settings", lambda: _settings())
    asyncio.run(_run(AuthFailureLimitMiddleware(app), _scope(path="/health")))
    asyncio.run(_run(AuthFailureLimitMiddleware(app), _scope(method="OPTIONS")))
    assert called == ["/private", "/health", "/private"]


def test_middleware_store_caido_no_tumba_la_peticion(monkeypatch):
    monkeypatch.setattr(rl, "get_settings", lambda: _settings())

    async def fake_count(*a, **kw):
        raise OSError("down")

    monkeypatch.setattr(rl, "_count_hits", fake_count)
    sent = asyncio.run(_run(AuthFailureLimitMiddleware(_app_status(200)), _scope()))
    assert sent[0]["status"] == 200


def test_middleware_sobre_limite_sin_firma_429(monkeypatch):
    monkeypatch.setattr(rl, "get_settings", lambda: _settings())

    async def fake_count(*a, **kw):
        return 30

    monkeypatch.setattr(rl, "_count_hits", fake_count)
    called = []

    async def app(scope, receive, send):
        called.append(1)

    sent = asyncio.run(_run(AuthFailureLimitMiddleware(app, limit=30), _scope()))
    assert called == []  # la app no llega a ejecutarse
    assert sent[0]["status"] == 429
    assert (b"retry-after", b"60") in sent[0]["headers"]
    assert sent[1]["body"] == b'{"detail":"Too many failed authentication attempts"}'


def test_middleware_401_se_registra_y_200_no(monkeypatch):
    monkeypatch.setattr(rl, "get_settings", lambda: _settings())

    async def fake_count(*a, **kw):
        return 0

    monkeypatch.setattr(rl, "_count_hits", fake_count)
    recorded = []

    async def fake_record(key, **kw):
        recorded.append(key)
        return 1, 60

    monkeypatch.setattr(rl, "_record_hit", fake_record)
    asyncio.run(_run(AuthFailureLimitMiddleware(_app_status(401)), _scope()))
    asyncio.run(_run(AuthFailureLimitMiddleware(_app_status(200)), _scope()))
    expected = "cavaai:authfail:" + hashlib.sha256(b"8.8.8.8").hexdigest()
    assert recorded == [expected]  # solo el 401 cuenta


def test_middleware_fallo_al_registrar_no_rompe(monkeypatch):
    monkeypatch.setattr(rl, "get_settings", lambda: _settings())

    async def fake_count(*a, **kw):
        return 0

    async def fake_record(*a, **kw):
        raise OSError("down")

    monkeypatch.setattr(rl, "_count_hits", fake_count)
    monkeypatch.setattr(rl, "_record_hit", fake_record)
    sent = asyncio.run(_run(AuthFailureLimitMiddleware(_app_status(401)), _scope()))
    assert sent[0]["status"] == 401  # la respuesta llega intacta
