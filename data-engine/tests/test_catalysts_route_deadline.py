"""/api/calendar/catalysts responde dentro del deadline de NASDAQ aunque EDGAR cuelgue.

Antes: los plazos 10-Q/10-K tenian su propio presupuesto de 20 s y la ruta
esperaba el mas lento de los tres conectores. Con la SEC caida (reintentos con
backoff) la respuesta tardaba 20 s medidos en local; el cliente del frontend
corta a los 15 s (RESEARCH_TIMEOUTS.GLOBAL_MS), asi que la pagina perdia
tambien los eventos que si habian llegado. Ahora EDGAR comparte el deadline del
rango NASDAQ (RANGE_DEADLINE_S): los tres conectores van en paralelo y la ruta
entera cabe en ese deadline.
"""

import asyncio
import time

from app.services import catalyst_calendar_service as svc
from app.services.connectors import earnings_calendar as connector
from tests.test_catalyst_calendar import _company, _route_client, db, engine  # noqa: F401


def test_catalysts_route_is_bounded_by_range_deadline_when_edgar_hangs(engine, db, monkeypatch):  # noqa: F811
    # La cache por dia del conector es estado de proceso: limpia antes y despues
    # para no heredar ni contaminar los dias de test_catalyst_calendar.
    connector._day_cache.clear()
    connector._day_failures.clear()  # noqa: SLF001
    svc._FAILED_UNTIL.clear()
    _company(db, "LOOP", 10)

    async def slow_cik(_ticker):
        await asyncio.sleep(3)
        return "0000000001"

    async def subs(_cik):
        return {}

    monkeypatch.setattr(svc, "_default_sec_fetchers", lambda: (slow_cik, subs))
    monkeypatch.setattr(connector, "RANGE_DEADLINE_S", 0.4)
    client, main = _route_client(
        engine,
        monkeypatch,
        earnings_rows=[{"symbol": "LOOP", "name": "Loop", "time": "time-pre-market"}],
        dividend_rows=[],
    )
    try:
        started = time.monotonic()
        res = client.get("/api/calendar/catalysts?desde=2026-10-14&hasta=2026-10-28")
        elapsed = time.monotonic() - started
    finally:
        main.app.dependency_overrides.clear()
        svc._FAILED_UNTIL.clear()
        connector._day_cache.clear()
        connector._day_failures.clear()  # noqa: SLF001
    assert res.status_code == 200
    # EDGAR dormia 3 s; con el deadline del rango (0,4 s) la ruta no lo espera.
    assert elapsed < 1.5, f"catalysts tardo {elapsed:.2f}s"
    body = res.json()
    assert body["status"] == "partial"
    assert [(e["ticker"], e["type"]) for e in body["events"]] == [("LOOP", "earnings")]
    assert any("EDGAR no disponible para LOOP" in e for e in body["errors"])
