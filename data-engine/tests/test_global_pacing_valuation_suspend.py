"""Pacing global Redis (Finnhub/GDELT) + suspension con cursor de valuation.

Medido en prod (31-oct-2026, piloto): 1.077 HTTP 429 de Finnhub en 10 min
(2 refresh_valuation_metrics en los 2 hilos de default) y GDELT con rachas
de 3-16 429 que abrian el disyuntor 30 min sin ingesta real. Cada proceso
llevaba su propio reloj; el ritmo AGREGADO violaba la cuota.
"""
from __future__ import annotations

import asyncio
import time
from datetime import date, timedelta

import pytest

from app.services.connectors.base import UpstreamRateLimited, get_with_retry
from app.services.connectors.global_pacing import GlobalPacer


class _FakeRedis:
    """Redis en memoria con la semantica de los dos scripts Lua del pacer."""

    def __init__(self):
        self.store: dict[str, str] = {}

    def eval(self, script, keys_count, *args):
        if keys_count == 2:  # claim slot
            slot_key, cooldown_key, now_ms, interval_ms, _ttl = args
            nxt = float(self.store.get(slot_key, "0"))
            blocked = float(self.store.get(cooldown_key, "0"))
            start = max(float(now_ms), nxt, blocked)
            self.store[slot_key] = f"{start + float(interval_ms):.0f}"
            return max(0.0, start - float(now_ms))
        # extend cooldown
        (cooldown_key, until_ms, _ttl) = args
        current = float(self.store.get(cooldown_key, "0"))
        if float(until_ms) > current:
            self.store[cooldown_key] = f"{float(until_ms):.0f}"
        return max(current, float(until_ms))

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ex=None):
        self.store[key] = value

    def delete(self, key):
        self.store.pop(key, None)

    def close(self):
        return None


def test_pacer_claims_se_espacian_globalmente():
    fake = _FakeRedis()
    pacer_a = GlobalPacer("prov", min_interval_seconds=0.05, redis_client_factory=lambda: fake)
    pacer_b = GlobalPacer("prov", min_interval_seconds=0.05, redis_client_factory=lambda: fake)

    async def main():
        marcas = []
        t0 = time.monotonic()
        for p in (pacer_a, pacer_b, pacer_a, pacer_b):
            await p.wait()
            marcas.append(time.monotonic() - t0)
        return marcas

    marcas = asyncio.run(main())
    # 4 huecos de 50 ms compartidos: la ultima salida no puede ser antes
    # de 3x50 ms; con relojes por proceso las 4 salian en rafaga.
    assert marcas[-1] >= 0.14, f"salidas sin espaciado global: {marcas}"


def test_pacer_cooldown_extend_only_y_visible_entre_procesos():
    fake = _FakeRedis()
    pacer_a = GlobalPacer("prov", min_interval_seconds=0.05, redis_client_factory=lambda: fake)
    pacer_b = GlobalPacer("prov", min_interval_seconds=0.05, redis_client_factory=lambda: fake)
    pacer_a.cool_down(30.0)
    assert pacer_b.blocked_for() > 25.0  # otro proceso ve la ventana
    pacer_b.cool_down(10.0)  # una ventana MENOR no acorta la vigente
    assert pacer_a.blocked_for() > 25.0


def test_pacer_sin_redis_degrada_a_pacing_local_no_a_rafaga():
    pacer = GlobalPacer("prov", min_interval_seconds=0.05, redis_client_factory=lambda: None)

    async def main():
        t0 = time.monotonic()
        for _ in range(3):
            await pacer.wait()
        return time.monotonic() - t0

    assert asyncio.run(main()) >= 0.09


def _resp_429(retry_after: str | None = None):
    import httpx

    headers = {"Retry-After": retry_after} if retry_after else {}
    return httpx.Response(429, headers=headers, request=httpx.Request("GET", "https://x"))


def test_upstream_rate_limited_conserva_retry_after():
    async def siempre_429():
        return _resp_429("45")

    with pytest.raises(UpstreamRateLimited) as excinfo:
        asyncio.run(get_with_retry(siempre_429, max_retries=0))
    assert excinfo.value.retry_after == 45.0


def test_backoff_con_jitter_respeta_retry_after_como_suelo():
    """Jitter en [0, expo] pero NUNCA por debajo del Retry-After del servidor."""
    sleeps: list[float] = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    import app.services.connectors.base as base_mod

    original = base_mod.asyncio.sleep
    base_mod.asyncio.sleep = fake_sleep
    try:
        calls = {"n": 0}

        async def dos_429_luego_ok():
            import httpx

            calls["n"] += 1
            if calls["n"] < 3:
                return _resp_429("0.3")
            return httpx.Response(200, json={}, request=httpx.Request("GET", "https://x"))

        asyncio.run(get_with_retry(dos_429_luego_ok, max_retries=2, base_seconds=0.5, jitter=True))
    finally:
        base_mod.asyncio.sleep = original
    assert len(sleeps) == 2
    assert all(s >= 0.3 for s in sleeps), f"Retry-After recortado: {sleeps}"
    assert sleeps[0] <= 0.5 and sleeps[1] <= 1.0 or sleeps[1] >= 0.3


def test_finnhub_429_marca_cooldown_global(monkeypatch):
    """El 429 de Finnhub cierra la ventana para TODOS los procesos."""
    import app.services.connectors.finnhub as finnhub_mod

    fake = _FakeRedis()
    monkeypatch.setattr(finnhub_mod, "_pacer", GlobalPacer(
        "finnhub", min_interval_seconds=0.01, redis_client_factory=lambda: fake
    ))
    monkeypatch.setattr(
        finnhub_mod, "get_settings",
        lambda: type("S", (), {"finnhub_api_key": "k", "redis_url": "redis://fake"})(),
    )

    async def sube_429(*args, **kwargs):
        raise UpstreamRateLimited("agotado", retry_after=42.0)

    monkeypatch.setattr(finnhub_mod, "get_with_retry", sube_429)
    client = finnhub_mod.FinnhubClient()
    with pytest.raises(UpstreamRateLimited):
        asyncio.run(client.metric("AAPL"))
    assert finnhub_mod.finnhub_blocked_for() > 35.0


def test_fetcher_yield_propaga_429_tipado(monkeypatch):
    """Antes el fetcher tragaba el 429 como 'fuente fallo' y el bucle seguia
    martilleando el resto del universo (1.077 429 medidos en 10 min)."""
    import app.services.valuation_metrics_service as svc

    monkeypatch.setattr(svc, "_network_forbidden_in_tests", lambda: None)
    settings = type("S", (), {"finnhub_api_key": "k", "redis_url": None})()
    monkeypatch.setattr("app.core.config.get_settings", lambda: settings)
    monkeypatch.setattr("app.services.connectors.finnhub.get_settings", lambda: settings)
    # _await_sync esta vetado bajo pytest (hermeticidad de red); se sustituye
    # por un runner directo: la corrutina es un mock local, no red.
    monkeypatch.setattr(
        "app.services.thesis_evidence_service._await_sync",
        lambda factory, timeout=30: asyncio.run(factory()),
    )

    async def metric_429(self, ticker, **kwargs):
        raise UpstreamRateLimited("agotado", retry_after=42.0)

    monkeypatch.setattr("app.services.connectors.finnhub.FinnhubClient.metric", metric_429)
    with pytest.raises(UpstreamRateLimited):
        svc.default_finnhub_yield_fetcher("AAPL")


def test_compute_aborta_con_cursor_al_429(monkeypatch=None):
    """Un 429 a mitad del universo suspende la corrida CON el ultimo ticker
    completado, en vez de quemar una llamada por empresa restante."""
    from app.services.valuation_metrics_service import (
        ValuationUniverseRateSuspended,
        compute_valuation_metrics,
    )
    from tests.test_propicks_prices import _db
    from tests.test_valuation_metrics import _seed_pb

    db = _db()
    first = _seed_pb(db, "AAA")
    _seed_pb(db, "ZZZ")
    llamadas = []

    def finnhub_429(ticker):
        llamadas.append(ticker)
        if ticker == "ZZZ":
            raise UpstreamRateLimited("agotado", retry_after=42.0)
        return None

    events = [{"date": (date(2026, 10, 27) - timedelta(days=100)).isoformat(), "amount": "0.8"}]
    with pytest.raises(ValuationUniverseRateSuspended) as excinfo:
        compute_valuation_metrics(
            db,
            [first] + [c for c in db.query(type(first)).filter_by(ticker="ZZZ")],
            as_of=date(2026, 10, 27),
            dividend_fetcher=lambda symbol: events,
            finnhub_yield_fetcher=finnhub_429,
        )
    # AAA completo, ZZZ suspende: el cursor es AAA y solo hubo 2 llamadas
    # (una por empresa), no una racha por el resto del universo.
    assert llamadas == ["AAA", "ZZZ"]
    assert excinfo.value.last_completed_ticker == "AAA"
    assert excinfo.value.retry_after == 42.0


def test_refresh_reanuda_tras_el_cursor():
    """start_after_ticker filtra el universo: no se repite lo ya hecho."""

    from app.services.valuation_metrics_service import refresh_valuation_metrics
    from tests.test_propicks_prices import _company, _db

    db = _db()
    for ticker in ("AAA", "BBB", "CCC"):
        db.add(_company(ticker))
    db.flush()
    result = refresh_valuation_metrics(
        db, as_of=date(2026, 10, 27), start_after_ticker="BBB",
        dividend_fetcher=lambda s: [], finnhub_yield_fetcher=lambda t: None,
    )
    assert result["companies"] == 1  # solo CCC


def test_actor_suspende_al_entrar_si_finnhub_esta_en_cooldown(monkeypatch):
    """Con la ventana 429 abierta, refresh_valuation_metrics se reencola tras
    el Retry-After SIN tocar la BD ni ocupar el hilo martilleando."""
    import dramatiq

    from app.workers import dramatiq_app

    monkeypatch.setattr(
        "app.services.connectors.finnhub.finnhub_blocked_for", lambda: 30.0
    )
    monkeypatch.setattr(dramatiq_app, "_retry_jitter_ms", lambda max_ms=30_000: 0)
    with pytest.raises(dramatiq.Retry) as excinfo:
        dramatiq_app.refresh_valuation_metrics(tenant_id=1)
    assert excinfo.value.delay >= 30_000


def test_actor_guarda_cursor_y_reencola_al_429_de_universo(monkeypatch):
    """429 a mitad del universo: cursor en Redis + Retry tras la ventana."""
    import dramatiq

    from app.services.valuation_metrics_service import ValuationUniverseRateSuspended
    from app.workers import dramatiq_app

    fake = _FakeRedis()
    monkeypatch.setattr(
        "app.services.connectors.finnhub.finnhub_blocked_for", lambda: 0.0
    )
    monkeypatch.setattr(dramatiq_app, "_retry_jitter_ms", lambda max_ms=30_000: 0)
    monkeypatch.setattr(dramatiq_app, "_redis_client", lambda: fake)
    monkeypatch.setattr(
        dramatiq_app, "_session",
        lambda *a, **k: type("FakeDB", (), {"close": lambda self: None})(),
    )
    monkeypatch.setattr(dramatiq_app, "acquire_job_lease", lambda *a, **k: "token")
    monkeypatch.setattr(dramatiq_app, "release_job_lease", lambda *a, **k: None)
    monkeypatch.setattr(dramatiq_app, "_rollback", lambda db: None)

    def _suspende(db, *, start_after_ticker=None, **kwargs):
        raise ValuationUniverseRateSuspended("AAA", 42.0)

    monkeypatch.setattr(
        "app.services.valuation_metrics_service.refresh_valuation_metrics", _suspende
    )
    with pytest.raises(dramatiq.Retry) as excinfo:
        dramatiq_app.refresh_valuation_metrics(tenant_id=1)
    assert excinfo.value.delay >= 42_000
    assert fake.store.get("valuation_metrics:cursor:1") == "AAA"


def test_sleep_async_inyectable_cubre_la_espera_del_hueco():
    """Con Redis devolviendo una espera real, wait() usa el sleep ASYNC
    inyectado y no el asyncio.sleep global (cluster gdelt rojo en CI con
    Redis real: la espera del cooldown no la cubria el fake_clock)."""
    fake = _FakeRedis()
    dormidas: list[float] = []

    async def _fake_sleep_async(seconds: float) -> None:
        dormidas.append(seconds)

    pacer = GlobalPacer(
        "prov-async",
        min_interval_seconds=5.0,
        redis_client_factory=lambda: fake,
        wall_clock=lambda: 1_000.0,
        sleep_async=_fake_sleep_async,
    )

    async def main():
        await pacer.wait()  # primer hueco: sin espera
        await pacer.wait()  # segundo: espera de 5 s SOLO via sleep_async

    t0 = time.monotonic()
    asyncio.run(main())
    assert time.monotonic() - t0 < 1.0, "la espera fue real: no uso el inyectable"
    assert dormidas == [5.0]


def test_sleep_async_por_defecto_es_asyncio_sleep():
    """Sin inyeccion, wait() duerme de verdad (comportamiento de prod)."""
    fake = _FakeRedis()
    pacer = GlobalPacer(
        "prov-real", min_interval_seconds=0.06, redis_client_factory=lambda: fake,
        wall_clock=lambda: 2_000.0,
    )

    async def main():
        await pacer.wait()
        await pacer.wait()

    t0 = time.monotonic()
    asyncio.run(main())
    assert time.monotonic() - t0 >= 0.05
