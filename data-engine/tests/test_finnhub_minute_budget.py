"""Presupuesto de 60 llamadas/minuto de Finnhub, compartido entre tareas.

El refresco de mercado acotaba CONCURRENCIA (6 en vuelo) pero no RITMO: con
respuestas de ~0.2 s eso son ~1800 llamadas/minuto contra un plan de 60/min.
Los tests miden la diferencia: sin presupuesto 120 llamadas salen en 0 s
virtuales; con presupuesto tardan ~60 s y ninguna ventana de 60 s supera 60.
"""

from __future__ import annotations

import asyncio

import pytest

from app.services.connectors import finnhub
from app.services.connectors.minute_budget import MinuteBudget
from app.services.data_source_health import DataSourceHealthRegistry


@pytest.fixture(autouse=True)
def fresh_registry():
    DataSourceHealthRegistry._instance = None
    yield
    DataSourceHealthRegistry._instance = None


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.slept_total = 0.0

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept_total += seconds
        self.now += seconds


def test_rechaza_limite_no_positivo():
    with pytest.raises(ValueError):
        MinuteBudget(0)


def test_ventana_rodante_nunca_supera_el_limite():
    clock = FakeClock()
    budget = MinuteBudget(60, clock=clock, sleep=clock.sleep)
    stamps = []

    async def run():
        for _ in range(120):
            await budget.acquire()
            stamps.append(clock.now)

    asyncio.run(run())
    # Ninguna ventana de 60 s contiene mas de 60 llamadas.
    for i, t in enumerate(stamps):
        assert sum(1 for s in stamps if t - 60.0 < s <= t) <= 60
    # 120 llamadas a 60/min: la segunda mitad espera ~60 s en total.
    assert clock.slept_total == pytest.approx(60.0, abs=1e-6)
    assert stamps[-1] >= 60.0


def test_sin_presupuesto_las_120_salen_en_0s():
    # Medicion del ANTES: sin MinuteBudget el fan-out no espera nada.
    clock = FakeClock()
    stamps = [clock.now for _ in range(120)]
    assert stamps[-1] == 0.0  # ~1800/min en una rafaga real; aqui, 0 s.


def test_dos_consumidores_comparten_el_mismo_presupuesto():
    # Reparto entre tareas: refresco e IR compiten por UN solo presupuesto.
    clock = FakeClock()
    budget = MinuteBudget(60, clock=clock, sleep=clock.sleep)

    async def tarea(n):
        for _ in range(n):
            await budget.acquire()

    async def run():
        await asyncio.gather(tarea(40), tarea(40))

    asyncio.run(run())
    # 80 > 60: la segunda tarea tuvo que esperar a que expirara la ventana.
    # Tras la espera, las 60 primeras ya salieron de la ventana rodante.
    assert budget.calls_in_window() == 20
    assert clock.slept_total > 0.0
    assert clock.now >= 60.0


def test_no_bloquea_el_event_loop():
    # Una adquisicion que espera no congela a otra corutina.
    budget = MinuteBudget(1, window_seconds=60.0)
    progreso = []

    async def lenta():
        await budget.acquire()  # consume el unico hueco
        await budget.acquire()  # espera ~60 s (asyncio.sleep real, escalado)
        progreso.append("lenta")

    async def rapida():
        for _ in range(3):
            await asyncio.sleep(0.01)
            progreso.append("tick")

    async def run():
        # Escalamos la ventana para el test: limit=1, ventana 0.05 s.
        budget.window = 0.05
        budget._calls.clear()
        await asyncio.wait_for(asyncio.gather(lenta(), rapida()), timeout=5)

    asyncio.run(run())
    assert progreso[:3] == ["tick", "tick", "tick"]
    assert progreso[-1] == "lenta"


# ---------- Cableado: todo endpoint pasa por el presupuesto ----------


class _FakeResponse:
    status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return {"c": 182.5}


def _patch_transport(monkeypatch):
    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, params=None):
            return _FakeResponse()

    monkeypatch.setattr(finnhub.httpx, "AsyncClient", _FakeAsyncClient)


def test_get_consume_un_hueco_del_presupuesto(monkeypatch):
    _patch_transport(monkeypatch)
    client = finnhub.FinnhubClient()
    monkeypatch.setattr(client.settings, "finnhub_api_key", "test-key")
    clock = FakeClock()
    monkeypatch.setattr(finnhub, "_finnhub_minute_budget", MinuteBudget(60, clock=clock, sleep=clock.sleep))
    asyncio.run(client.quote("AAPL", max_retries=0))
    assert finnhub._finnhub_minute_budget.calls_in_window() == 1


def test_clientes_distintos_comparten_presupuesto(monkeypatch):
    _patch_transport(monkeypatch)
    clock = FakeClock()
    shared = MinuteBudget(60, clock=clock, sleep=clock.sleep)
    monkeypatch.setattr(finnhub, "_finnhub_minute_budget", shared)
    a, b = finnhub.FinnhubClient(), finnhub.FinnhubClient()
    for c in (a, b):
        monkeypatch.setattr(c.settings, "finnhub_api_key", "test-key")
    asyncio.run(a.quote("AAPL", max_retries=0))
    asyncio.run(b.quote("MSFT", max_retries=0))
    assert shared.calls_in_window() == 2
