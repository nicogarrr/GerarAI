"""Tests del deadline de rango, la cache diaria y el singleflight del conector NASDAQ.

Motivacion (16 oct 2026): /api/calendar/catalysts superaba los 10 s en prod
(30 consultas NASDAQ en oleadas de 4, un AsyncClient nuevo por dia, sin
deadline de rango ni cache) y la pagina moria con un 504 de plataforma.

Run from data-engine/:
    pytest tests/test_earnings_calendar_deadline.py -v
"""

import asyncio
import time
from datetime import date, timedelta

import pytest

from app.services.connectors import earnings_calendar as connector


def run_async(coroutine):
    return asyncio.run(coroutine)


@pytest.fixture(autouse=True)
def _clean_module_cache(monkeypatch):
    # Los tests de deadline razonan con oleadas de 4 dias: se fija explicito.
    monkeypatch.setattr(connector, "RANGE_CONCURRENCY", 4)
    connector._day_cache.clear()  # noqa: SLF001 - estado de proceso del conector
    connector._day_failures.clear()  # noqa: SLF001
    connector._day_inflight.clear()  # noqa: SLF001
    yield
    connector._day_cache.clear()  # noqa: SLF001
    connector._day_failures.clear()  # noqa: SLF001
    connector._day_inflight.clear()  # noqa: SLF001


def test_deadline_preserves_resolved_days_and_marks_the_rest():
    """6 dias a ~5s por dia con concurrencia 4 y deadline de 8s:
    la primera oleada se conserva y los 2 dias restantes se declaran,
    nunca se rellenan."""

    async def fake_day(day, _client):
        await asyncio.sleep(5)
        return [{"symbol": "X", "date": day.isoformat()}]

    async def probe():
        start = date(2026, 9, 14)  # lunes
        return await connector._fetch_days(  # noqa: SLF001 - se prueba la unidad
            fake_day, start, start + timedelta(days=5), object(), deadline_s=8.0
        )

    t0 = time.monotonic()
    events, errors = run_async(probe())
    elapsed = time.monotonic() - t0
    assert len(events) == 4, "la primera oleada (4 dias) se conserva"
    assert len(errors) == 2, "los otros 2 dias se declaran, no se rellenan"
    assert all("deadline del rango" in e for e in errors)
    assert elapsed < 9.5, f"el rango entero queda acotado por el deadline: {elapsed:.1f}s"


def test_deadline_error_is_explicit_and_distinct_from_provider_failure():
    """Un dia que falla en el proveedor (None) y otro sin presupuesto llevan
    mensajes distintos: el operador debe poder diferenciarlos."""

    async def fake_day(day, _client):
        if day.day == 15:
            return None  # proveedor caido ese dia
        await asyncio.sleep(5)
        return [{"symbol": "X", "date": day.isoformat()}]

    async def probe():
        start = date(2026, 9, 14)
        return await connector._fetch_days(  # noqa: SLF001
            fake_day, start, start + timedelta(days=6), object(), deadline_s=8.0
        )

    events, errors = run_async(probe())
    assert len(events) == 4
    assert any("calendario no disponible" in e for e in errors)
    assert any("deadline del rango" in e for e in errors)


def test_singleflight_and_daily_cache_on_the_production_path(monkeypatch):
    """Sin cliente inyectado (camino de prod), dos rangos concurrentes sobre
    los mismos dias disparan UNA consulta por dia, y un rango posterior se
    sirve de la cache diaria."""
    calls = {"n": 0}

    async def fake_day(day, _client):
        calls["n"] += 1
        await asyncio.sleep(0.05)
        return [{"symbol": "X", "date": day.isoformat()}]

    monkeypatch.setattr(connector, "fetch_earnings_day", fake_day)

    async def probe():
        start = date(2026, 9, 14)
        first, second = await asyncio.gather(
            connector.fetch_earnings_range(start, start + timedelta(days=2)),
            connector.fetch_earnings_range(start, start + timedelta(days=2)),
        )
        third = await connector.fetch_earnings_range(start, start + timedelta(days=2))
        return first, second, third

    first, second, third = run_async(probe())
    assert calls["n"] == 3, f"singleflight: 1 consulta por dia, no {calls['n']}"
    assert first["status"] == second["status"] == third["status"] == "ok"
    assert first["count"] == second["count"] == third["count"] == 3


def test_injected_client_bypasses_cache(monkeypatch):
    """Con cliente inyectado (tests/hermetico) no hay cache: cada llamada
    consulta de verdad."""
    calls = {"n": 0}

    async def fake_day(day, _client):
        calls["n"] += 1
        return [{"symbol": "X", "date": day.isoformat()}]

    monkeypatch.setattr(connector, "fetch_earnings_day", fake_day)

    async def probe():
        start = date(2026, 9, 14)
        client = object()  # no-None: camino inyectado
        await connector.fetch_earnings_range(start, start, client)
        await connector.fetch_earnings_range(start, start, client)

    run_async(probe())
    assert calls["n"] == 2


def test_pooled_client_is_reused_between_calls():
    first = connector._pooled_client()  # noqa: SLF001
    second = connector._pooled_client()  # noqa: SLF001
    assert first is second


def test_default_concurrency_fits_two_weeks_in_the_cold_deadline(monkeypatch):
    """Medido en prod (19 oct 2026): 15 dias frios con concurrencia 4 no cabian
    en 8 s. Con el valor por defecto actual, 15 dias a ~1 s caben en 2 oleadas
    dentro de un deadline que con 4 (4 oleadas) no alcanzaria."""
    monkeypatch.undo()  # valor por defecto del modulo, no el fijado por el fixture
    assert connector.RANGE_CONCURRENCY >= 8

    async def fake_day(day, _client):
        await asyncio.sleep(1)
        return [{"symbol": "X", "date": day.isoformat()}]

    async def probe():
        start = date(2026, 10, 19)
        return await connector._fetch_days(  # noqa: SLF001
            fake_day, start, start + timedelta(days=14), object(), deadline_s=3.0
        )

    events, errors = run_async(probe())
    assert len(events) == 15 and errors == []
