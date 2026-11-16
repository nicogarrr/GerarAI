"""Un 429 de GDELT es throttling por IP, no un fallo de salud de la fuente.

Medido en prod: rachas de 3-16 respuestas 429 abrian el breaker de salud
(umbral 3 consecutivos) aunque el cliente ya honra Retry-After (inline
acotado, ventana por IP en clase/Redis y reencolado dramatiq): la fuente
aparecia "failing" estando sana. Estos tests fijan que una tormenta de 429
nunca abre el breaker y que un error real (red) si degrada.
"""

import asyncio

import httpx
import pytest

from app.services.connectors import gdelt as g
from app.services.data_source_health import CircuitState, get_data_source_registry


@pytest.fixture
def sin_throttle(monkeypatch):
    async def _no_throttle(self):
        pass

    monkeypatch.setattr(g.GDELTClient, "_throttle", _no_throttle)


def _client_429() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(429, headers={"Retry-After": "30"}))
    )


def test_tormenta_429_nunca_abre_el_breaker_de_salud(sin_throttle):
    registry = get_data_source_registry()
    status = registry.get_status("gdelt")
    tormenta = status.failure_threshold + 7  # muy por encima del umbral
    try:

        async def run():
            async with _client_429() as client:
                gdelt = g.GDELTClient(client, max_429_retries=0)
                for _ in range(tormenta):
                    with pytest.raises(g.GdeltRateLimited):
                        await gdelt.news_search("EXAMPLE")

        asyncio.run(run())
        assert status.consecutive_failures == 0
        assert status.state == CircuitState.CLOSED
        assert status.can_attempt()
    finally:
        # El registry es singleton de proceso: dejarlo limpio.
        registry.record_success("gdelt")


def test_error_de_red_si_degrada_la_fuente(sin_throttle):
    registry = get_data_source_registry()
    status = registry.get_status("gdelt")

    def boom(_):
        raise httpx.ConnectError("boom")

    try:

        async def run():
            async with httpx.AsyncClient(transport=httpx.MockTransport(boom)) as client:
                with pytest.raises(httpx.ConnectError):
                    await g.GDELTClient(client).news_search("EXAMPLE")

        asyncio.run(run())
        assert status.consecutive_failures == 1
    finally:
        registry.record_success("gdelt")
