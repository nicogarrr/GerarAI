"""fetch_filing_deadlines: tope por peticion, presupuesto de tiempo y fallos en cache corta.

Antes: una llamada por emisor sin tope, reintentos sin presupuesto total y sin
memoria de fallos: con la SEC caida, cada carga del calendario repetia todo.
Ahora devuelve parcial marcado (``partial``/``unavailable`` + errores visibles).
"""

import asyncio
import time
from datetime import date

import pytest

from app.services import catalyst_calendar_service as svc


@pytest.fixture(autouse=True)
def _reset():
    svc._FAILED_UNTIL.clear() if hasattr(svc, "_FAILED_UNTIL") else None
    yield
    svc._FAILED_UNTIL.clear() if hasattr(svc, "_FAILED_UNTIL") else None


def _run(tickers, cik, subs, **kw):
    return asyncio.run(svc.fetch_filing_deadlines(
        set(tickers), date(2026, 1, 1), date(2026, 12, 31),
        cik_fetcher=cik, submissions_fetcher=subs, **kw))


def test_max_tickers_per_request_caps_calls_and_marks_partial():
    calls = []

    async def cik(t):
        calls.append(t)
        return None

    async def subs(c):
        return None

    result = _run([f"T{i:03d}" for i in range(200)], cik, subs)
    assert len(calls) <= svc.MAX_DEADLINE_TICKERS
    assert result["status"] in {"partial", "unavailable"}
    assert any("no consultado" in e for e in result["errors"])
    assert len(result["errors"]) == 200  # nada se descarta en silencio


def test_total_time_budget_returns_partial_not_hang():
    async def cik(t):
        await asyncio.sleep(5)
        return "1"

    async def subs(c):
        return {}

    start = time.monotonic()
    result = _run([f"T{i}" for i in range(8)], cik, subs, budget_seconds=0.3)
    assert time.monotonic() - start < 2
    assert result["status"] == "unavailable"
    assert len(result["errors"]) == 8


def test_recent_failure_is_cached_briefly():
    calls = []

    async def cik(t):
        calls.append(t)
        raise ConnectionError("down")

    async def subs(c):
        return {}

    first = _run(["AAA", "BBB"], cik, subs)
    second = _run(["AAA", "BBB"], cik, subs)
    assert len(calls) == 2  # la segunda carga no vuelve a llamar
    assert first["status"] == second["status"] == "unavailable"
    assert len(second["errors"]) == 2
