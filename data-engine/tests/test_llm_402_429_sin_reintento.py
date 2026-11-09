"""Un 402 (sin saldo) o un 429 del proveedor no se reintenta en bucle: el 402 abre un corte por clave para
que el resto del job no vuelva a llamar, y quien lo pide (la tesis v2) se para en el primer 429. Cliente HTTP
simulado: ninguna petición sale de la máquina."""
from __future__ import annotations

import asyncio
import time

import httpx
import pytest

from app.llm import LLMRequest, Message, base
from app.llm.adapters import OpenAICompatibleProvider
from app.llm.errors import ProviderHTTPError
from app.services.expert_team import thesis_v2 as T
from app.services.expert_team.service import provider_reasoner
from tests.test_thesis_v2 import _ctx


def _provider(handler, *, key: str = "k", **kw) -> tuple[OpenAICompatibleProvider, list[str]]:
    posts: list[str] = []

    async def counted(request: httpx.Request) -> httpx.Response:
        posts.append(request.url.path)
        return await handler(request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(counted))
    p = OpenAICompatibleProvider(api_key=key, base_url="https://opencode.ai/zen/go/v1", default_model="m",
                                 provider_name="opencode-go", client=client, max_retries=kw.pop("max_retries", 2),
                                 **kw)
    return p, posts


def _req() -> LLMRequest:
    return LLMRequest(messages=[Message("user", "hola")])


def _status(code: int, body: str = "{}", headers: dict | None = None):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(code, text=body, headers=headers or {})
    return handler


def test_402_una_sola_peticion_y_el_resto_del_job_no_llama():
    p, posts = _provider(_status(402, '{"error":"insufficient balance"}'))
    for _ in range(3):
        with pytest.raises(ProviderHTTPError) as exc:
            asyncio.run(p.complete(_req()))
        assert exc.value.status_code == 402
    assert len(posts) == 1  # antes: un 402 por cada llamada del job
    kinds = {b["kind"] for b in base.breaker_snapshot()}
    assert "payment_required" in kinds


def test_402_de_una_clave_no_corta_otra_clave():
    p1, posts1 = _provider(_status(402), key="sin-saldo")
    with pytest.raises(ProviderHTTPError):
        asyncio.run(p1.complete(_req()))

    ok_body = ('{"choices":[{"message":{"content":"hola"},"finish_reason":"stop"}],'
               '"usage":{"prompt_tokens":1,"completion_tokens":1}}')
    p2, posts2 = _provider(_status(200, ok_body), key="con-saldo")
    assert asyncio.run(p2.complete(_req())).text == "hola"
    assert len(posts1) == 1 and len(posts2) == 1


def test_402_respeta_retry_after():
    p, _ = _provider(_status(402, headers={"retry-after": "30"}))
    with pytest.raises(ProviderHTTPError):
        asyncio.run(p.complete(_req()))
    (snap,) = [b for b in base.breaker_snapshot() if b["kind"] == "payment_required"]
    assert 0 < float(snap["seconds_remaining"]) <= 30  # type: ignore[arg-type]


def test_429_sin_reintento_si_se_pide():
    p, posts = _provider(_status(429, '{"error":"rate limited"}'))
    p.retry_rate_limited = False  # type: ignore[attr-defined]
    with pytest.raises(ProviderHTTPError) as exc:
        asyncio.run(p.complete(_req()))
    assert exc.value.status_code == 429 and len(posts) == 1


def test_429_plano_conserva_su_reintento_por_defecto():
    p, posts = _provider(_status(429, '{"error":"rate limited"}'), max_retries=2)
    with pytest.raises(ProviderHTTPError):
        asyncio.run(p.complete(_req()))
    assert len(posts) == 3  # comportamiento de siempre para quien no lo pide


def test_tesis_completa_con_proveedor_simulado_402_hace_una_peticion():
    p, posts = _provider(_status(402))
    p.retry_rate_limited = False  # type: ignore[attr-defined]
    ctx = _ctx()
    res = asyncio.run(T.write_thesis(reasoner=provider_reasoner(p, db=None, temperature=0.0), ctx=ctx))
    assert len(posts) == 1
    assert res.status == "provider_stopped" and res.stopped == T.STOP_HTTP[402]
    assert set(res.missing) == {k for k, *_ in T.active_sections(ctx)}


def test_tesis_completa_con_proveedor_simulado_lento_respeta_el_plazo(monkeypatch):
    monkeypatch.setattr(T, "TOTAL_DEADLINE_SECONDS", 0.5)

    async def lento(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(3600)
        return httpx.Response(200)

    # Plazo del adaptador mayor que el de la tesis: manda el total de la redacción.
    p, posts = _provider(lento, timeout_seconds=600, total_timeout_seconds=900, max_retries=1)
    ctx = _ctx()
    t0 = time.monotonic()
    res = asyncio.run(T.write_thesis(reasoner=provider_reasoner(p, db=None, temperature=0.0), ctx=ctx))
    assert time.monotonic() - t0 < 1.2
    assert res.status == "timeout" and set(res.missing.values()) == {T.TIMEOUT_REASON}
    assert len(posts) == 2  # una por parte, ninguna después del plazo
