"""Banco HTTP local opt-in. Nunca apunta a producción ni admite URL externa.

LATENCY_REPORT=/tmp/latencia.json PYTHONPATH=.:tests python -m pytest \
    tests/test_screen_endpoint_latency.py -s -q

Semilla artificial identificada, SQLite, TestClient ASGI, red bloqueada.
Primera muestra separada, luego 30 secuenciales por endpoint y tamaño.
No mide Next/RSC/TLS, producción, red ni proveedores externos.
"""
from __future__ import annotations

import json
import os
import platform
import socket
import subprocess
import time
from pathlib import Path

import pytest
from sqlalchemy import event

from app.core.auth import ResearchPrincipal
from app.core.database import engine
from scripts.endpoint_latency_stats import summarize
from tests.test_perf_guard_query_budgets import perf_world  # noqa: F401

# Lecturas de pantallas: no se ejecutan cerebro/tesis/valor intrínseco/DCA.
# Parámetros {lead}/{watch} se resuelven únicamente con la semilla artificial.
ENDPOINTS = {
    "/api/portfolio/positions?page=1&page_size=200": ["inicio", "cartera", "temas"],
    "/api/portfolio/summary": ["inicio", "cartera", "watchlist"],
    "/api/watchlist": ["inicio", "watchlist", "temas", "screener"],
    "/api/alerts/rules?active=true&limit=100&offset=0": ["inicio"],
    "/api/alerts?limit=3": ["inicio"],
    "/api/watchlist/metrics/{lead}": ["watchlist"],
    "/api/companies/basics?tickers={watch}": ["watchlist", "inicio"],
    "/api/watchlist/monitor?tickers={watch}": ["watchlist"],
    "/api/market/changes?tickers={watch}": ["watchlist"],
    "/api/market/themes": ["temas"],
    "/api/market/flows/themes": ["temas"],
    "/api/bottlenecks": ["temas"],
    "/api/market/flows/themes/utilities": ["temas"],
    "/api/market/flows/themes/centros-de-datos": ["temas"],
    "/api/market/flows/themes/defensa": ["temas"],
    "/api/market/indices": ["screener"],
    "/api/screeners/real?limit=20": ["screener"],
    "/api/portfolio/transactions/page?limit=50&offset=0": ["cartera"],
    "/api/portfolio/snapshots?page=1&page_size=200": ["cartera"],
    "/api/portfolio/tearsheet": ["cartera"],
    "/api/portfolio/forecast": ["cartera"],
    "/api/portfolio/dividends": ["cartera"],
    "/api/portfolio/dividends/projection": ["cartera"],
    "/api/portfolio/data-quality": ["cartera"],
    "/api/companies/{lead}": ["research"],
    "/api/companies/{lead}/snapshot": ["research"],
    "/api/companies/{lead}/facts?limit=250": ["research"],
    "/api/companies/{lead}/metrics/calculated": ["research"],
    "/api/companies/{lead}/ttm": ["research"],
    "/api/companies/{lead}/key-stats": ["research"],
    "/api/companies/{lead}/financial-terminal": ["research"],
    "/api/companies/{lead}/share-capital": ["research"],
    "/api/companies/{lead}/management-alignment": ["research"],
    "/api/companies/{lead}/management-credibility": ["research"],
    "/api/companies/{lead}/decision-lessons": ["research"],
    "/api/companies/{lead}/decision-lessons/taxonomy": ["research"],
    "/api/companies/{lead}/decision-journal/trades": ["research"],
    "/api/companies/{lead}/expectation-reality": ["research"],
    "/api/watchlist/news-preparing/{lead}": ["research"],
    "/api/ownership/schedule-13dg?ticker={lead}": ["research"],
    "/api/ownership/institutions/{lead}": ["research"],
    "/api/ownership/funds/{lead}": ["research"],
    "/api/investors/holders/{lead}": ["research"],
    "/api/insider/filings?ticker={lead}&limit=20": ["research"],
    "/api/insider/summary?ticker={lead}": ["research"],
    "/api/insider/ownership-signals?ticker={lead}": ["research"],
    "/api/politicians/ticker/{lead}": ["research"],
    "/api/paper-trading/proposals?ticker={lead}&limit=20": ["research"],
    "/api/screeners/custom-metrics": ["screeners"],
    "/api/companies/{lead}/peers/comparison": ["research"],
    "/api/companies/{lead}/decision-journal": ["research"],
    "/api/reviews?ticker={lead}": ["research"],
    "/api/alerts?ticker={lead}&include_snoozed=true": ["research"],
    "/api/sources/documents?ticker={lead}&scope=all&include_chunks=false": ["research"],
    "/api/sources/audits?ticker={lead}": ["research"],
    "/api/news?ticker={lead}&limit=30": ["research", "inicio"],
    "/api/screeners/screens": ["screener"],
    "/api/screeners/metric-coverage": ["screener"],
    "/api/market/movers?limit=10": ["screener"],
    "/api/calendar/catalysts": ["calendario"],
    "/api/calendar/followed": ["calendario", "inicio"],
    "/api/calendar/earnings": ["calendario"],
    "/api/calendar/dividends": ["calendario"],
    "/api/calendar/ipos": ["calendario"],
}


@pytest.mark.skipif(not os.environ.get("LATENCY_REPORT"), reason="Banco local opt-in")
def test_screen_endpoint_latency(perf_world, monkeypatch):
    # Un intento de red queda registrado, no se confunde con éxito del proveedor.
    blocked = []
    def deny_network(*args, **kwargs):
        blocked.append("network_attempt")
        raise OSError("Banco aislado: red externa desactivada")
    monkeypatch.setattr(socket.socket, "connect", deny_network)
    monkeypatch.setattr(socket, "create_connection", deny_network)
    report = {
        "environment": "[medido] fixture artificial local, SQLite + TestClient ASGI; red bloqueada",
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "python": platform.python_version(),
        "n_warm": 30,
        "exclusions": ["Next/RSC/TLS", "cerebro", "tesis", "valor intrínseco", "DCA",
                       "proveedores en vivo", "datos de Nico"],
        "results": [],
    }
    sql = {"queries": 0, "elapsed": 0.0, "start": 0.0}
    def before(*args):
        sql["queries"] += 1
        sql["start"] = time.perf_counter()
    def after(*args):
        sql["elapsed"] += time.perf_counter() - sql["start"]
    event.listen(engine, "before_cursor_execute", before)
    event.listen(engine, "after_cursor_execute", after)
    try:
        for path, screens in ENDPOINTS.items():
            for size in ("small", "large"):
                tenant = perf_world[size]
                perf_world["state"]["principal"] = ResearchPrincipal(
                    user_id="latency-fixture", tenant_external_id=tenant["external"])
                url = path.format(lead=tenant["lead"], watch=",".join(tenant["tickers"][::2]))
                samples = []
                network_before = len(blocked)
                for _ in range(31):
                    sql.update(queries=0, elapsed=0.0)
                    started = time.perf_counter()
                    response = perf_world["client"].get(url)
                    elapsed = (time.perf_counter() - started) * 1000
                    samples.append(dict(status=response.status_code, elapsed_ms=elapsed,
                                        queries=sql["queries"], bytes=len(response.content),
                                        sql_ms=sql["elapsed"] * 1000))
                row = dict(path=path, screens=screens, fixture=size,
                           positions=4 if size == "small" else 16,
                           first=samples[0], warm=summarize(samples[1:]), samples=samples[1:],
                           blocked_network_attempts=len(blocked) - network_before)
                report["results"].append(row)
                # Persistir después de cada endpoint permite recuperar un banco interrumpido.
                Path(os.environ["LATENCY_REPORT"]).write_text(
                    json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    finally:
        event.remove(engine, "before_cursor_execute", before)
        event.remove(engine, "after_cursor_execute", after)
