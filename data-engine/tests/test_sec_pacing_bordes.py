"""Bordes de sec_pacing: fabrica Redis, cuota diferida y fallback local del pacer.

Pacers FRESCOS por test con relojes/sleep inyectados por constructor (contrato
de GlobalPacer); el modulo asyncio de sec_pacing se dobla con el truco
SimpleNamespace de la casa (no contaminar el asyncio global). Cero red, cero
Redis real, cero sleeps reales medidos. El test de _check_long_cooldown usa
monotonic REAL coherente (cool_down y blocked_for deben hablar del mismo
reloj: cool_down usa el inyectado pero blocked_for usa time.monotonic real).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
import pytest

from app.services.connectors import sec_pacing
from app.services.connectors.sec_pacing import SecPacer, SecQuotaDeferred


@pytest.fixture
def _settings_frescos():
    from app.core.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _pacer_fresco(**kwargs) -> SecPacer:
    """SecPacer aislado: sin Redis, monotonic fijo, sleeps sync anulados."""
    kwargs.setdefault("min_interval_seconds", 0.15)
    kwargs.setdefault("redis_client_factory", lambda: None)
    kwargs.setdefault("monotonic", lambda: 1000.0)
    kwargs.setdefault("sleep", lambda seconds: None)
    return SecPacer("test-sec", **kwargs)


def test_redis_sin_url_configurada_devuelve_none(monkeypatch, _settings_frescos):
    """17: sin REDIS_URL no hay cliente compartido."""
    monkeypatch.setenv("REDIS_URL", "")
    assert sec_pacing._redis() is None


def test_rate_limited_publica_cooldown_y_difiere_ventanas_largas(monkeypatch):
    """32-33 y 86: 429 con Retry-After 120 -> cool_down(120) y SecQuotaDeferred."""
    enfriado: list[float] = []
    # reset: el fixture autouse de conftest (reset_sec_client_state) lo llama
    # al cerrar el test; el doble debe aceptarlo.
    monkeypatch.setattr(
        sec_pacing,
        "pacer",
        SimpleNamespace(cool_down=enfriado.append, reset=lambda: None),
    )
    respuesta = httpx.Response(429, headers={"retry-after": "120"})
    with pytest.raises(SecQuotaDeferred) as excinfo:
        sec_pacing.rate_limited(respuesta)
    assert enfriado == [120.0]
    assert excinfo.value.retry_after == 120.0
    assert str(excinfo.value) == "SEC 429: shared cooldown, retry after 120.0s"


def test_check_long_cooldown_difiere_cuando_quedan_mas_de_60s():
    """40: cooldown restante > 60s -> SecQuotaDeferred con el restante.

    Reloj REAL (monotonic por defecto): cool_down y blocked_for deben hablar
    del mismo reloj; _check_long_cooldown se prueba directo para no entrar en
    el bucle de espera de wait_sync.
    """
    import time

    pacer = _pacer_fresco(monotonic=time.monotonic)
    pacer.cool_down(120.0)
    with pytest.raises(SecQuotaDeferred) as excinfo:
        pacer._check_long_cooldown()
    assert 60.0 < excinfo.value.retry_after <= 120.0


def test_rate_limited_retry_after_infinito_cae_a_60s(monkeypatch):
    """83: Retry-After 'inf' parsea a infinito (float('inf') pasa el clamp de
    _raw_retry_after); la ventana no finita se sustituye por 60.0, se publica
    ese cooldown y NO difiere (60 no supera el tope inline de 60)."""
    enfriado: list[float] = []
    monkeypatch.setattr(
        sec_pacing,
        "pacer",
        SimpleNamespace(cool_down=enfriado.append, reset=lambda: None),
    )
    respuesta = httpx.Response(429, headers={"retry-after": "inf"})
    assert sec_pacing.rate_limited(respuesta) is None
    assert enfriado == [60.0]


def test_wait_sync_sin_cooldown_reserva_y_pasa():
    """43-44: sin cooldown, wait_sync delega en el pacer global y reserva."""
    pacer = _pacer_fresco()
    assert pacer.wait_sync() is None
    assert pacer._local_next == pytest.approx(1000.15)


def test_wait_async_fallback_local_espera_lo_reservado(monkeypatch):
    """49->63 y 63-68: sin Redis, la 2a llamada espera el hueco reservado."""
    sleeps: list[float] = []

    async def _sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(
        sec_pacing, "asyncio", SimpleNamespace(**(vars(asyncio) | {"sleep": _sleep}))
    )
    pacer = _pacer_fresco()
    asyncio.run(pacer.wait())
    asyncio.run(pacer.wait())
    assert sleeps == [pytest.approx(0.15)]


def test_wait_async_con_redis_y_slot_libre_no_espera(monkeypatch):
    """59->61: Redis vivo con slot libre (wait_ms=0) -> vuelve sin esperar."""
    sleeps: list[float] = []

    async def _sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(
        sec_pacing, "asyncio", SimpleNamespace(**(vars(asyncio) | {"sleep": _sleep}))
    )
    redis_falso = SimpleNamespace(eval=lambda *args: 0)
    pacer = _pacer_fresco(redis_client_factory=lambda: redis_falso)
    asyncio.run(pacer.wait())
    assert sleeps == []


def test_wait_async_con_redis_espera_lo_del_slot(monkeypatch):
    """58-60: Redis vivo con slot ocupado -> espera exactamente wait_ms/1000."""
    sleeps: list[float] = []

    async def _sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(
        sec_pacing, "asyncio", SimpleNamespace(**(vars(asyncio) | {"sleep": _sleep}))
    )
    redis_falso = SimpleNamespace(eval=lambda *args: 250)
    pacer = _pacer_fresco(redis_client_factory=lambda: redis_falso)
    asyncio.run(pacer.wait())
    assert sleeps == [0.25]
