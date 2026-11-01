"""Tests negativos de los 4 bugs que el piloto encontro en la PR #3727.

Cada test falla contra el codigo original (rojo) y pasa con la correccion
(verde): persistencia del progreso, deadline en _throttle, pacing por
intento HTTP en Finnhub y ritmo global real en GDELT.
"""
from __future__ import annotations

import asyncio
from datetime import date, timedelta

import pytest

from app.services.connectors.base import UpstreamRateLimited


def test_progreso_comprometido_sobrevive_al_rollback_del_actor():
    """Bug 1: el actor hace rollback al suspenderse por 429; sin commit por
    empresa las metricas procesadas se perdian y el cursor las saltaba para
    siempre. Ahora cada empresa es una pagina atomica comprometida."""
    from app.services.valuation_metrics_service import (
        ValuationUniverseRateSuspended,
        refresh_valuation_metrics,
    )
    from tests.test_propicks_prices import _db
    from tests.test_valuation_metrics import _metric, _seed_pb

    db = _db()
    aaa = _seed_pb(db, "AAA")
    _seed_pb(db, "ZZZ")
    db.commit()  # datos de partida fuera de la transaccion de la corrida

    def finnhub_429(ticker):
        if ticker == "ZZZ":
            raise UpstreamRateLimited("agotado", retry_after=42.0)
        return None

    events = [{"date": (date(2026, 10, 27) - timedelta(days=100)).isoformat(), "amount": "0.8"}]
    with pytest.raises(ValuationUniverseRateSuspended) as excinfo:
        refresh_valuation_metrics(
            db,
            as_of=date(2026, 10, 27),
            dividend_fetcher=lambda symbol: events,
            finnhub_yield_fetcher=finnhub_429,
        )
    assert excinfo.value.last_completed_ticker == "AAA"
    db.rollback()  # exactamente lo que hace el actor al capturar la suspension
    # AAA quedo comprometida: el cursor no avanza sobre metricas perdidas.
    assert _metric(db, aaa, "price_to_book") is not None


def test_gdelt_throttle_termina_con_redis_devolviendo_siempre_lo_mismo(monkeypatch):
    """Bug 2: el bloqueo remoto se calculaba UNA vez fuera del while; un TTL
    remoto constante <= MAX_RETRY_AFTER dormia ese delta en bucle infinito.
    Ahora se recalcula en el bucle y se acota con un deadline monotono."""
    import app.services.connectors.gdelt as gdelt_mod

    reloj = [1000.0]
    monkeypatch.setattr(gdelt_mod.time, "monotonic", lambda: reloj[0])
    sleeps: list[float] = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        reloj[0] += seconds
        if len(sleeps) > 20:
            raise RuntimeError("bucle infinito: falta el deadline monotono")

    async def noop_wait():
        return None

    monkeypatch.setattr(gdelt_mod.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(gdelt_mod._gdelt_pacer, "blocked_for_remote", lambda: 5.0)
    monkeypatch.setattr(gdelt_mod._gdelt_pacer, "wait", noop_wait)
    gdelt_mod.GDELTClient._next_allowed_at = 0.0
    gdelt_mod.GDELTClient._blocked_until = 0.0

    asyncio.run(gdelt_mod.GDELTClient()._throttle())
    # Duerme la ventana remota vista al entrar (5 s) y sale: ni infinito ni cero.
    assert abs(sum(sleeps) - 5.0) < 1e-6, f"esperas: {sleeps}"


def test_gdelt_throttle_reclama_hueco_global_en_cada_peticion(monkeypatch):
    """Bug 4: GDELT solo compartia el cooldown 429; nunca reclamaba hueco en
    el pacer global, asi que dos procesos salian a la vez cada uno con su
    reloj local. Ahora _throttle pasa por el pacer en cada peticion."""
    import app.services.connectors.gdelt as gdelt_mod

    llamadas: list[int] = []

    async def wait_espia():
        llamadas.append(1)

    monkeypatch.setattr(gdelt_mod._gdelt_pacer, "wait", wait_espia)
    monkeypatch.setattr(gdelt_mod._gdelt_pacer, "blocked_for_remote", lambda: 0.0)
    monkeypatch.setattr(gdelt_mod.time, "monotonic", lambda: 1000.0)
    gdelt_mod.GDELTClient._next_allowed_at = 0.0
    gdelt_mod.GDELTClient._blocked_until = 0.0

    asyncio.run(gdelt_mod.GDELTClient()._throttle())
    assert llamadas == [1]


def test_finnhub_pacer_se_aplica_en_cada_intento_http(monkeypatch):
    """Bug 3: el pacer se aplicaba una vez antes de get_with_retry y los
    reintentos inline eludian el ritmo global. Ahora cada intento HTTP pasa
    por el hueco compartido."""
    import httpx

    import app.services.connectors.base as base_mod
    import app.services.connectors.finnhub as finnhub_mod

    esperas: list[int] = []

    class _PacerEspia:
        async def wait(self):
            esperas.append(1)

        def cool_down(self, seconds):
            return None

    monkeypatch.setattr(finnhub_mod, "_pacer", _PacerEspia())
    monkeypatch.setattr(
        finnhub_mod,
        "get_settings",
        lambda: type("S", (), {"finnhub_api_key": "k", "redis_url": None})(),
    )

    intentos: list[int] = []

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, params=None):
            intentos.append(1)
            req = httpx.Request("GET", "https://x")
            if len(intentos) < 3:
                return httpx.Response(429, headers={"Retry-After": "0"}, request=req)
            return httpx.Response(200, json={"c": 1}, request=req)

    async def noop_sleep(seconds):
        return None

    monkeypatch.setattr(finnhub_mod.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(base_mod.asyncio, "sleep", noop_sleep)

    payload = asyncio.run(finnhub_mod.FinnhubClient().quote("AAPL", max_retries=2))
    assert payload == {"c": 1}
    assert len(intentos) == 3
    # Un pacer.wait por intento HTTP; antes era 1 en total y 2 eludian el limite.
    assert len(esperas) == 3, f"pacer.wait llamado {len(esperas)} veces en {len(intentos)} intentos"


def test_finnhub_con_redis_caido_mantiene_pacing_local(monkeypatch):
    """Piloto: fallback_local=False dejaba Finnhub SIN ritmo si Redis fallaba
    (proteccion desactivada en prod solo por los tests). El pacer real del
    modulo mantiene el fallback local activo; los tests inyectan reloj y
    sleep falsos en vez de desactivar la proteccion."""
    import app.services.connectors.finnhub as finnhub_mod

    pacer = finnhub_mod._pacer  # el pacer REAL del modulo
    reloj = [1000.0]
    esperas: list[float] = []

    def fake_sleep(seconds):
        esperas.append(seconds)
        reloj[0] += seconds

    monkeypatch.setattr(pacer, "_monotonic", lambda: reloj[0])
    monkeypatch.setattr(pacer, "_sleep", fake_sleep)
    monkeypatch.setattr(pacer, "_factory", lambda: None)  # Redis caido

    async def dos_llamadas():
        await pacer.wait()
        await pacer.wait()

    asyncio.run(dos_llamadas())
    # La segunda llamada espera el intervalo: sin fallback local saldria en
    # rafaga y el ritmo agregado con Redis caido volveria a ser ilimitado.
    assert esperas, "fallback local desactivado: rafaga sin ritmo con Redis caido"
    assert abs(sum(esperas) - pacer.min_interval_seconds) < 1e-6, f"esperas: {esperas}"
