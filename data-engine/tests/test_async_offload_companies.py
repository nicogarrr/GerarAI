"""Las rutas de refresh de companies no ejecutan trabajo sincrono en el loop.

resolve_company, la ingesta FMP/SEC/ESEF y el refresh de WACC mezclan
sqlalchemy y clientes de proveedor sincronos: deben correr en un hilo del
pool (run_in_threadpool), con la corutina del servicio puenteado via
run_from_any_context. El detector es simple: un helper sync invocado desde
el hilo del event loop ve un loop en marcha; desde un hilo worker, no.
"""

import asyncio
from types import SimpleNamespace

from fastapi.testclient import TestClient

import main
from app.core.csrf import generate_csrf_token
from app.core.database import init_db

client = TestClient(main.app)
client.headers["X-CSRF-Token"] = generate_csrf_token()  # token CSRF como el frontend (VAL-SEC-001)


class _OffLoopProbe:
    """Registra si el helper sync corrio con un event loop en el hilo."""

    def __init__(self):
        self.calls: list[bool] = []

    def sync_fn(self, *args, **kwargs):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            self.calls.append(True)  # sin loop: hilo worker, correcto
        else:
            self.calls.append(False)  # con loop: event loop, bloqueante
        return SimpleNamespace(id=1, ticker="PROBE")


def test_refresh_wacc_runs_sync_work_off_the_event_loop(monkeypatch):
    init_db()
    probe = _OffLoopProbe()
    monkeypatch.setattr("app.api.routes.companies.resolve_company", probe.sync_fn)

    async def fake_refresh(self, db, company):  # noqa: ARG001
        return {"status": "ok", "ticker": company.ticker}

    monkeypatch.setattr(
        "app.api.routes.companies.WaccInputService.refresh", fake_refresh
    )
    response = client.post("/api/companies/PROBE/refresh/wacc")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "ok"
    assert probe.calls and all(probe.calls)


def test_refresh_sec_runs_sync_work_off_the_event_loop(monkeypatch):
    init_db()
    probe = _OffLoopProbe()
    monkeypatch.setattr("app.api.routes.companies.resolve_company", probe.sync_fn)

    async def fake_refresh(self, db, company):  # noqa: ARG001
        return {
            "status": "ok",
            "ticker": company.ticker,
            "provider": "sec",
            "source_document_id": 1,
            "facts_imported": 5,
        }

    monkeypatch.setattr(
        "app.api.routes.companies.FinancialIngestionService.refresh_from_sec",
        fake_refresh,
    )
    monkeypatch.setattr(
        "app.api.routes.companies.FinancialIngestionService.latest_periods",
        lambda self, db, company: {"FY2024": "2024-12-31"},  # noqa: ARG005
    )
    monkeypatch.setattr(
        "app.api.routes.companies.FinancialIngestionService.valuation_input_ready",
        lambda self, db, company: True,  # noqa: ARG005
    )
    response = client.post("/api/companies/PROBE/refresh/sec")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["facts_imported"] == 5
    assert body["statements_imported"] == 0
    assert body["valuation_input_ready"] is True
    assert probe.calls and all(probe.calls)
