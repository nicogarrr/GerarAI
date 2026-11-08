"""Huecos de cobertura en company_events y research_assistant (lote 5).

Medicion previa con los tests que referencian cada modulo: company_events
82 % (toda la ruta timeline, el 404 de /events y la ruta /filings) y
research_assistant 93 % (validador ticket-sin-ticker, ticker heredado del
contexto de pagina y los dos LookupError -> 404). Estos tests cierran esas
ramas con servicios doblados en el modulo de ruta.

Que NO se prueba aqui: nada de HTTP, middleware ni auth; ningun servicio
real (CompanyEventsService, resolve_company, answer, synthesize/LLM,
guide_context van doblados); ninguna fuente externa (Finnhub, SEC, GDELT,
Yahoo); ni hilos de verdad: run_in_threadpool se ejecuta dentro de
asyncio.run y solo se certifica el mapeo funcion -> resultado, no la
concurrencia. Las fechas extremas (OverflowError) se fuerzan doblando
local_today, sin reloj real.
"""

from __future__ import annotations

import asyncio
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from app.api.routes import company_events as events_route
from app.api.routes import research_assistant as assistant_route

COMPANY = SimpleNamespace(ticker="ASTS", currency="USD")


def run_async(coro):
    return asyncio.run(coro)


# --- company_events: timeline --------------------------------------------


def test_timeline_compania_desconocida_es_404(monkeypatch):
    monkeypatch.setattr(events_route, "resolve_company", lambda db, t: None)
    with pytest.raises(HTTPException) as exc:
        events_route.get_company_timeline_events("NOPE", desde=None, hasta=None, db=Mock())
    assert exc.value.status_code == 404


def test_timeline_desde_posterior_a_hasta_es_400(monkeypatch):
    monkeypatch.setattr(events_route, "resolve_company", lambda db, t: COMPANY)
    with pytest.raises(HTTPException) as exc:
        events_route.get_company_timeline_events(
            "ASTS", desde=date(2026, 5, 1), hasta=date(2026, 1, 1), db=Mock()
        )
    assert exc.value.status_code == 400


def test_timeline_recorta_a_30_anios(monkeypatch):
    """Un rango mayor que TIMELINE_MAX_DAYS se recorta por abajo."""
    monkeypatch.setattr(events_route, "resolve_company", lambda db, t: COMPANY)
    monkeypatch.setattr(events_route, "stored_timeline_events", lambda db, c, s, e: [])
    monkeypatch.setattr(events_route, "stored_holding", lambda db, c: None)
    result = events_route.get_company_timeline_events(
        "ASTS", desde=date(1990, 1, 1), hasta=date(2026, 1, 1), db=Mock()
    )
    esperado = date(2026, 1, 1) - events_route.timedelta(days=events_route.TIMELINE_MAX_DAYS)
    assert result["desde"] == esperado.isoformat()
    assert result["hasta"] == "2026-01-01"
    assert result["ticker"] == "ASTS"


def test_timeline_fecha_fuera_de_rango_es_400(monkeypatch):
    """0001-01-01 menos 183 dias no existe: OverflowError -> 400, no 500."""
    monkeypatch.setattr(events_route, "resolve_company", lambda db, t: COMPANY)
    monkeypatch.setattr(events_route, "local_today", lambda: date(1, 1, 1))
    with pytest.raises(HTTPException) as exc:
        events_route.get_company_timeline_events("ASTS", desde=None, hasta=None, db=Mock())
    assert exc.value.status_code == 400


# --- company_events: /events y /filings -----------------------------------


def test_events_compania_desconocida_es_404(monkeypatch):
    monkeypatch.setattr(events_route, "resolve_company", lambda db, t: None)
    with pytest.raises(HTTPException) as exc:
        run_async(events_route.get_company_events("NOPE", db=Mock()))
    assert exc.value.status_code == 404


def test_events_devuelve_lo_del_servicio(monkeypatch):
    monkeypatch.setattr(events_route, "resolve_company", lambda db, t: COMPANY)
    monkeypatch.setattr(events_route, "run_from_any_context", lambda x: x)

    class Servicio:
        def __init__(self, db):
            pass

        def get_events(self, company):
            return {"ticker": company.ticker, "history": []}

    monkeypatch.setattr(events_route, "CompanyEventsService", Servicio)
    result = run_async(events_route.get_company_events("ASTS", db=Mock()))
    assert result == {"ticker": "ASTS", "history": []}


def test_filings_compania_desconocida_es_404(monkeypatch):
    monkeypatch.setattr(events_route, "resolve_company", lambda db, t: None)
    with pytest.raises(HTTPException) as exc:
        run_async(events_route.get_company_filings("NOPE", db=Mock()))
    assert exc.value.status_code == 404


def test_filings_devuelve_lo_del_servicio(monkeypatch):
    monkeypatch.setattr(events_route, "resolve_company", lambda db, t: COMPANY)
    monkeypatch.setattr(events_route, "run_from_any_context", lambda x: x)

    class Servicio:
        def __init__(self, db):
            pass

        def get_filings(self, company):
            return {"ticker": company.ticker, "filings": []}

    monkeypatch.setattr(events_route, "CompanyEventsService", Servicio)
    result = run_async(events_route.get_company_filings("ASTS", db=Mock()))
    assert result == {"ticker": "ASTS", "filings": []}


# --- research_assistant ----------------------------------------------------


def test_ticket_sin_ticker_es_error_de_validacion():
    """review_id sin ticker: el validador lo rechaza antes de tocar la ruta."""
    with pytest.raises(ValueError, match="ticket"):
        assistant_route.AssistantRequest(
            mode="explore", question="que dice esta review", review_id=7
        )


def _respuesta_dict(mode="explore"):
    return {
        "mode": mode,
        "status": "answered",
        "answer": "respuesta",
        "sections": [],
        "citations": [],
        "missing_data": [],
        "suggested_next_steps": [],
        "review_id": None,
    }


def test_assistant_hereda_el_ticker_del_contexto_de_pagina(monkeypatch):
    """Explore sin ticker: el ticker de la pagina resuelta completa la pregunta."""
    visto = {}
    pagina = SimpleNamespace(company=SimpleNamespace(ticker="ASTS"), echo=lambda: {"v": 1})
    monkeypatch.setattr(assistant_route, "resolve_page_context", lambda db, p: pagina)
    monkeypatch.setattr(
        assistant_route, "answer", lambda db, payload: visto.setdefault("ticker", payload.ticker)
    )

    async def sintetiza(db, payload, baseline):
        return _respuesta_dict()

    monkeypatch.setattr(assistant_route, "synthesize", sintetiza)
    payload = assistant_route.AssistantRequest(mode="explore", question="que sabes de esto")
    result = run_async(assistant_route.research_assistant(payload, db=Mock()))
    assert visto["ticker"] == "ASTS"
    assert result.context == {"v": 1}


def test_assistant_lookup_error_es_404(monkeypatch):
    """LookupError del pipeline (ticker no resuelto en el servicio) -> 404."""
    monkeypatch.setattr(assistant_route, "resolve_page_context", lambda db, p: None)

    def roto(db, payload):
        raise LookupError("company not found")

    monkeypatch.setattr(assistant_route, "answer", roto)
    payload = assistant_route.AssistantRequest(
        mode="explore", question="que sabes", ticker="NOPE"
    )
    with pytest.raises(HTTPException) as exc:
        run_async(assistant_route.research_assistant(payload, db=Mock()))
    assert exc.value.status_code == 404


def test_guide_context_lookup_error_es_404(monkeypatch):
    def roto(db, ticker):
        raise LookupError("company not found")

    monkeypatch.setattr(assistant_route, "guide_context", roto)
    with pytest.raises(HTTPException) as exc:
        assistant_route.research_guide_context(ticker="NOPE", db=Mock())
    assert exc.value.status_code == 404
