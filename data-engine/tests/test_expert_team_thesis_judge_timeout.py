"""Tesis guardada del equipo: decir cuándo el juez no llegó a tiempo.

El chat ya avisa «el juez no llegó a tiempo» (#4093), pero la pantalla de la
tesis guardada y su historial solo decían «Sin veredicto», igual que cuando no
hubo choque que resolver. Ahora la respuesta lleva ``judge_timed_out`` (en la
tesis y en cada corrida del historial) cuando el veredicto grabado vino de un
juez que se quedó sin tiempo. Solo lectura: no se reescriben corridas viejas.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.routes.thesis import latest_expert_thesis
from app.core.config import get_settings
from app.models.entities import Base, Tenant, WorkflowRun


def _result(verdict: dict | None) -> dict:
    return {
        "context": {"tenant_id": 1, "ticker": "MSFT", "mode": "thesis"},
        "plan": ["fundamental", "risk"],
        "reports": [
            {
                "expert": "fundamental",
                "status": "ok",
                "summary": "Crece",
                "stance": "bullish",
                "claims": [{"text": "Ingresos 245", "citations": ["ev-1"], "reason": ""}],
            },
            {
                "expert": "risk",
                "status": "ok",
                "summary": "Deuda",
                "stance": "bearish",
                "claims": [{"text": "Deuda alta", "citations": ["ev-1"], "reason": ""}],
            },
        ],
        "sources": [{"id": "ev-1", "table": "financial_facts", "source": "SEC EDGAR", "period": "FY", "date": "2025"}],
        "conflicts": [{"type": "stance", "positive": ["fundamental"], "negative": ["risk"]}],
        **({"verdict": verdict} if verdict is not None else {}),
    }


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Tenant(id=1, external_id="a"))
        session.flush()
        base = datetime(2026, 11, 1, 10, 0, tzinfo=UTC)
        verdicts = [
            None,  # id 1: corrida vieja sin veredicto grabado
            {"source": "judge", "label": "bullish", "rationale": "r"},  # id 2
            {"label": "neutral", "rationale": "", "source": "timeout"},  # id 3
            {"label": "neutral", "rationale": "", "source": "timeout"},  # id 4: la última
        ]
        session.add_all(
            [
                WorkflowRun(
                    tenant_id=1,
                    workflow_name="ExpertTeamThesisWorkflow",
                    status="completed",
                    input_payload={"ticker": "MSFT", "params": {}},
                    result_payload={"status": "completed", "result": _result(v)},
                    finished_at=base + timedelta(hours=i),
                )
                for i, v in enumerate(verdicts)
            ]
        )
        session.commit()
        session.info["tenant_id"] = 1
        yield session


@pytest.fixture(autouse=True)
def flag_on(monkeypatch):
    monkeypatch.setenv("EXPERT_TEAM_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_latest_thesis_says_judge_ran_out_of_time(db):
    out = latest_expert_thesis("MSFT", db)
    assert out is not None and out.run_id == 4
    assert out.verdict is None
    assert out.judge_timed_out is True


def test_history_marks_only_runs_whose_judge_timed_out(db):
    out = latest_expert_thesis("MSFT", db)
    assert out is not None
    assert [(h.run_id, h.judge_timed_out) for h in out.history] == [(3, True), (2, False), (1, False)]
    assert out.history[1].verdict == "a favor"


def test_judge_verdict_or_no_verdict_is_not_a_timeout(db):
    out = latest_expert_thesis("MSFT", db, run=2)
    assert out is not None and out.verdict is not None and out.judge_timed_out is False
    old = latest_expert_thesis("MSFT", db, run=1)
    assert old is not None and old.verdict is None and old.judge_timed_out is False


def test_stored_run_is_not_rewritten(db):
    latest_expert_thesis("MSFT", db)
    run = db.get(WorkflowRun, 1)
    assert run is not None and "verdict" not in run.result_payload["result"]
