"""Rutas LLM/pesadas: el trabajo sincrono no corre en el event loop.

Sonda: un helper sync invocado desde el hilo del event loop ve un loop en
marcha; desde un hilo worker (run_in_threadpool), no. Los servicios cuya
corutina puentea con run_from_any_context se dobla con una funcion sync
que devuelve la corutina: la llamada al servicio tambien queda medida.
"""

import asyncio

from fastapi.testclient import TestClient

import main
from app.core.database import SessionLocal, init_db
from app.models import Document

client = TestClient(main.app)


def _off_loop() -> bool:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return True
    return False


def test_thesis_debate_sync_work_off_the_event_loop(monkeypatch):
    init_db()
    calls: list[bool] = []

    def fake_latest(self, db, ticker):  # noqa: ARG001
        calls.append(_off_loop())
        from types import SimpleNamespace

        return SimpleNamespace(id=None, thesis_markdown="# t", executive_summary="s")

    monkeypatch.setattr("app.api.routes.thesis.ThesisService.latest", fake_latest)
    monkeypatch.setattr(
        "app.api.routes.thesis.resolve_company",
        lambda db, ticker: (calls.append(_off_loop())  # noqa: ARG005
                            or __import__("types").SimpleNamespace(id=None, ticker=ticker)),
    )

    async def fake_debate(ticker, markdown):  # noqa: ARG001
        return {
            "ticker": ticker, "bull_case": "b", "bear_case": "s",
            "verdict": "hold", "verdict_rationale": "r", "llm_calls": 2,
            "degraded": False, "model": "m", "materiality_score": 0,
            "portfolio_weight": 0.0,
        }

    monkeypatch.setattr(
        "app.services.thesis_debate_service.debate_thesis", fake_debate
    )
    response = client.post("/api/thesis/PROBE/debate")
    assert response.status_code == 200, response.text
    assert response.json()["verdict"] == "hold"
    assert calls and all(calls)


def test_research_assistant_sync_work_off_the_event_loop(monkeypatch):
    init_db()
    calls: list[bool] = []

    def fake_resolve(db, page):  # noqa: ARG001
        calls.append(_off_loop())
        return None

    def fake_answer(db, payload):  # noqa: ARG001
        calls.append(_off_loop())
        return {"baseline": True}

    async def fake_synthesize(db, payload, baseline):  # noqa: ARG001
        return {
            "mode": "explore", "status": "answered", "answer": "a",
            "sections": [], "citations": [], "missing_data": [],
            "suggested_next_steps": [], "review_id": None,
        }

    monkeypatch.setattr(
        "app.api.routes.research_assistant.resolve_page_context", fake_resolve
    )
    monkeypatch.setattr("app.api.routes.research_assistant.answer", fake_answer)
    monkeypatch.setattr("app.api.routes.research_assistant.synthesize", fake_synthesize)
    response = client.post("/api/research/assistant", json={"mode": "explore", "question": "que es esta empresa"})
    assert response.status_code == 200, response.text
    assert calls and all(calls)


def test_historical_stress_service_call_off_the_event_loop(monkeypatch):
    init_db()
    calls: list[bool] = []

    def fake_build(self, db, ticker=None):  # noqa: ARG001
        calls.append(_off_loop())

        async def _result():
            return {"status": "ok"}

        return _result()

    monkeypatch.setattr(
        "app.services.historical_stress_service.HistoricalStressService.build",
        fake_build,
    )
    response = client.get("/api/risk/historical-stress")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "ok"
    assert calls and all(calls)


def test_extract_document_kpis_off_the_event_loop(monkeypatch):
    init_db()
    db = SessionLocal()
    try:
        db.add(Document(title="10-K", source_type="sec_filing"))
        db.commit()
        document_id = db.execute(
            __import__("sqlalchemy").select(Document.id).limit(1)
        ).scalar_one()
    finally:
        db.close()
    calls: list[bool] = []

    def fake_extract(self, db, document):  # noqa: ARG001
        calls.append(_off_loop())

        async def _result():
            return []

        return _result()

    monkeypatch.setattr(
        "app.services.kpi_extraction_service.KPIExtractionService.extract_document",
        fake_extract,
    )
    response = client.post(f"/api/sources/documents/{document_id}/extract-kpis")
    assert response.status_code == 200, response.text
    assert calls and all(calls)
