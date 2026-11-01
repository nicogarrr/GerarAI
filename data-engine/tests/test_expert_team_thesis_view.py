"""GET /thesis/{ticker}/experts: la última tesis guardada del equipo de expertos.

La tesis con expertos (#4036) se guardaba en workflow_runs pero no había
forma de leerla después. Ahora el endpoint la devuelve lista para pintar:
sección por experto con sus afirmaciones válidas y [n], fuentes numeradas
con enlace si lo hay. 404 con EXPERT_TEAM_ENABLED apagado; null si no hay
ninguna; nunca la de otro tenant. Solo lectura, sin LLM ni red.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.routes.thesis import latest_expert_thesis
from app.core.config import get_settings
from app.models.entities import Base, Tenant, WorkflowRun


def _result(tenant: int, *, ticker: str = "MSFT", text: str = "Ingresos 245 mil millones") -> dict:
    return {
        "context": {"tenant_id": tenant, "ticker": ticker, "mode": "thesis"},
        "plan": ["fundamental", "valuation", "news"],
        "reports": [
            {"expert": "fundamental", "status": "ok", "summary": "Crece", "stance": "bullish",
             "claims": [{"text": text, "citations": ["ev-1"], "reason": ""},
                        {"text": "Cifra sin fuente", "citations": [], "reason": "uncited"}]},
            {"expert": "valuation", "status": "timeout", "summary": "", "claims": []},
            {"expert": "news", "status": "ok", "summary": "x", "claims": []},
        ],
        "sources": [{"id": "ev-1", "table": "financial_facts", "source": "SEC EDGAR", "period": "FY", "date": "2025",
                     "url": "https://www.sec.gov/Archives/edgar/data/789019/x-index.htm"}],
        "conflicts": [{"type": "stance", "positive": ["fundamental"], "negative": ["risk"]}],
        "verdict": {"source": "judge", "label": "bullish", "rationale": "Pesa más el crecimiento."},
    }


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([Tenant(id=1, external_id="a"), Tenant(id=2, external_id="b")])
        session.flush()
        finished = datetime(2026, 11, 1, 20, 0, tzinfo=UTC)

        def run(tenant, status, result, ticker="MSFT"):
            return WorkflowRun(tenant_id=tenant, workflow_name="ExpertTeamThesisWorkflow", status=status,
                               input_payload={"ticker": ticker, "params": {}},
                               result_payload={"status": status, "result": result} if result else None,
                               finished_at=finished)

        session.add_all([
            run(1, "completed", _result(1, text="Antigua")),
            run(1, "completed", _result(1)),
            run(1, "running", None),
            run(2, "completed", _result(2, text="DEL OTRO TENANT")),
            run(1, "completed", _result(1, ticker="AAPL", text="Apple"), ticker="AAPL"),
        ])
        session.commit()
        session.info["tenant_id"] = 1
        yield session


@pytest.fixture()
def flag_on(monkeypatch):
    monkeypatch.setenv("EXPERT_TEAM_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _clear_settings():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_flag_off_is_404(db):
    with pytest.raises(HTTPException) as exc:
        latest_expert_thesis("MSFT", db)
    assert exc.value.status_code == 404


def test_latest_completed_run_for_the_ticker(db, flag_on):
    out = latest_expert_thesis("msft", db)
    assert out is not None
    assert out.ticker == "MSFT"
    assert out.plan == ["fundamental", "valuation", "news"]
    fundamental, valuation, news = out.sections
    assert fundamental.expert == "fundamental" and fundamental.summary == "Crece"
    assert [c.text for c in fundamental.claims] == ["Ingresos 245 mil millones"]  # sin la descartada
    assert fundamental.claims[0].refs == [1]
    assert valuation.status == "timeout" and valuation.claims == []
    assert news.status == "no_data"
    assert out.sources[0].n == 1
    assert out.sources[0].title.startswith("Estados financieros · SEC EDGAR")
    assert out.sources[0].url and out.sources[0].url.startswith("https://www.sec.gov/")
    assert out.conflicts and "Fundamental" in out.conflicts[0]
    assert out.verdict is not None and out.verdict.label == "a favor"


def test_never_another_tenants_run(db, flag_on):
    out = latest_expert_thesis("MSFT", db)
    assert out is not None
    assert all("DEL OTRO TENANT" not in c.text for s in out.sections for c in s.claims)


def test_no_saved_run_is_null(db, flag_on):
    assert latest_expert_thesis("TSLA", db) is None


def test_english_labels(db, flag_on, monkeypatch):
    from app.core import i18n

    monkeypatch.setattr(i18n, "current_language", lambda: "en")
    out = latest_expert_thesis("MSFT", db)
    assert out is not None
    assert out.sources[0].title.startswith("Financial statements")
    assert out.verdict is not None and out.verdict.label == "positive"


def test_unsafe_source_url_is_dropped(db, flag_on):
    run = db.query(WorkflowRun).filter(WorkflowRun.id == 2).one()
    payload = dict(run.result_payload or {})
    payload["result"]["sources"][0]["url"] = "javascript:alert(1)"
    run.result_payload = payload
    from sqlalchemy.orm.attributes import flag_modified

    flag_modified(run, "result_payload")
    db.commit()
    out = latest_expert_thesis("MSFT", db)
    assert out is not None and out.sources[0].url is None
