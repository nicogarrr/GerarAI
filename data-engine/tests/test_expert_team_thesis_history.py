"""GET /thesis/{ticker}/experts: historial corto de corridas anteriores del equipo.

La pantalla solo enseñaba la última tesis del equipo de expertos. Ahora la
respuesta trae ``history``: las corridas COMPLETADAS anteriores del mismo
ticker y tenant, de la más reciente a la más antigua (máx. 5), cada una con
su fecha, el veredicto del juez, qué expertos respondieron y cuáles no
respondieron a tiempo. Solo lectura, sin LLM ni red.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.routes.thesis import latest_expert_thesis
from app.core.config import get_settings
from app.models.entities import Base, Tenant, WorkflowRun


def _result(tenant: int, *, ticker: str = "MSFT", label: str = "bullish", timeout: bool = True) -> dict:
    return {
        "context": {"tenant_id": tenant, "ticker": ticker, "mode": "thesis"},
        "plan": ["fundamental", "valuation", "news"],
        "reports": [
            {
                "expert": "fundamental",
                "status": "ok",
                "summary": "Crece",
                "stance": "bullish",
                "claims": [{"text": "Ingresos 245", "citations": ["ev-1"], "reason": ""}],
            },
            {
                "expert": "valuation",
                "status": "timeout" if timeout else "ok",
                "summary": "",
                "claims": [] if timeout else [{"text": "PER 30", "citations": ["ev-1"], "reason": ""}],
            },
            {"expert": "news", "status": "ok", "summary": "x", "claims": []},
        ],
        "sources": [
            {"id": "ev-1", "table": "financial_facts", "source": "SEC EDGAR", "period": "FY", "date": "2025"}
        ],
        "conflicts": [],
        "verdict": {"source": "judge", "label": label, "rationale": "r"},
    }


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([Tenant(id=1, external_id="a"), Tenant(id=2, external_id="b")])
        session.flush()
        base = datetime(2026, 11, 1, 10, 0, tzinfo=UTC)

        def run(tenant, status, result, hours, ticker="MSFT"):
            return WorkflowRun(
                tenant_id=tenant,
                workflow_name="ExpertTeamThesisWorkflow",
                status=status,
                input_payload={"ticker": ticker, "params": {}},
                result_payload={"status": status, "result": result} if result else None,
                finished_at=base + timedelta(hours=hours),
            )

        session.add_all(
            [
                run(1, "completed", _result(1, label="bearish", timeout=False), 0),  # id 1
                run(1, "completed", _result(1, label="neutral"), 1),  # id 2
                run(1, "failed", None, 2),  # id 3
                run(2, "completed", _result(2), 3),  # id 4 otro tenant
                run(1, "completed", _result(1, ticker="AAPL"), 4, ticker="AAPL"),  # id 5 otro ticker
                run(1, "completed", _result(1), 5),  # id 6 la última
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


def test_history_lists_earlier_runs_latest_first(db):
    out = latest_expert_thesis("MSFT", db)
    assert out is not None and out.run_id == 6
    assert [h.run_id for h in out.history] == [2, 1]  # sin la última, sin fallidas/otro tenant/otro ticker
    newer, older = out.history
    assert newer.finished_at is not None and older.finished_at is not None
    assert newer.finished_at > older.finished_at
    assert newer.verdict == "neutral" and older.verdict == "en contra"
    assert newer.answered == ["fundamental"] and newer.timed_out == ["valuation"]
    assert older.answered == ["fundamental", "valuation"] and older.timed_out == []


def test_history_is_short(db):
    base = datetime(2026, 10, 1, tzinfo=UTC)
    db.add_all(
        [
            WorkflowRun(
                tenant_id=1,
                workflow_name="ExpertTeamThesisWorkflow",
                status="completed",
                input_payload={"ticker": "TSLA", "params": {}},
                result_payload={"status": "completed", "result": _result(1, ticker="TSLA")},
                finished_at=base + timedelta(days=i),
            )
            for i in range(9)
        ]
    )
    db.commit()
    out = latest_expert_thesis("TSLA", db)
    assert out is not None
    assert len(out.history) == 5
    ids = [h.run_id for h in out.history]
    assert ids == sorted(ids, reverse=True) and out.run_id not in ids


def test_single_run_has_empty_history(db):
    out = latest_expert_thesis("AAPL", db)
    assert out is not None and out.history == []


def test_history_verdict_in_english(db, monkeypatch):
    from app.core import i18n

    monkeypatch.setattr(i18n, "current_language", lambda: "en")
    out = latest_expert_thesis("MSFT", db)
    assert out is not None and [h.verdict for h in out.history] == ["neutral", "negative"]
