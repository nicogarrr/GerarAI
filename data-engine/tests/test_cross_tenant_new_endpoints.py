"""Aislamiento entre tenants en los endpoints nuevos o cambiados desde el 28-oct.

Complementa test_cross_tenant_probes.py (recursos con CRUD por id) con las
lecturas nuevas: política DCA, proyección de ahorro, bandeja de cambios de
tesis, ejecuciones DCA manuales por id, propuestas simuladas filtradas por
ticker con su tesis anclada, tesis/memo de una empresa y regenerar el informe
fiscal. El tenant A deja datos; el tenant B nunca los ve ni los cambia.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import Company, Tenant
from app.models.entities import (
    DcaEvaluationRun,
    ResearchReview,
    ThesisChange,
    ThesisVersion,
    WatchItem,
)
from app.models.paper_trading import PaperTrade
from tests.auth_helpers import auth_settings, signed_request
from tests.test_cross_tenant_probes import _no_network

SECRET = "cross-tenant-new-endpoints-secret-with-32-chars"
NOW = datetime(2026, 10, 28, 12, tzinfo=UTC)


@pytest.fixture()
def env(monkeypatch):
    _no_network(monkeypatch)
    init_db()
    monkeypatch.setattr(
        auth_module, "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET, app_env="test"),
    )
    from app.workers import dramatiq_app

    monkeypatch.setattr(dramatiq_app.broker, "enqueue", lambda message, delay=None: message)
    suffix = uuid4().hex[:8]
    client = TestClient(main.app)
    # Ticker propio por test: nada que ver con lo que dejen otros tests.
    ticker = f"ZT{suffix[:4].upper()}"

    def call(tenant: str, method: str, path: str, json_body=None, params=None):
        return signed_request(
            client, SECRET, f"{tenant}-{suffix}", f"user-{tenant}-{suffix}",
            method, path, json_body=json_body, params=params,
        )

    def tenant_id(tenant: str) -> int:
        assert call(tenant, "GET", "/api/settings/dca").status_code == 200
        with SessionLocal() as db:
            return db.scalar(select(Tenant.id).where(Tenant.external_id == f"{tenant}-{suffix}"))

    with SessionLocal() as db:
        company = Company(ticker=ticker, name=f"Empresa {ticker}", exchange="NASDAQ", currency="USD",
                          sector="Test", industry="Test", company_type="standard", valuation_model="standard_dcf")
        db.add(company)
        db.commit()
        company_id = company.id
    return {"call": call, "tenant_id": tenant_id, "ticker": ticker, "company_id": company_id}


def _write(tenant_id: int, *rows) -> list[int]:
    with SessionLocal() as db:
        db.info["tenant_id"] = tenant_id
        db.add_all(rows)
        db.commit()
        return [row.id for row in rows]


def _thesis(tenant_id: int, company_id: int, version: int, summary: str) -> ThesisVersion:
    return ThesisVersion(
        tenant_id=tenant_id, company_id=company_id, version=version, status="draft",
        thesis_markdown=f"# {summary}", executive_summary=summary, rating="watch",
        created_at=NOW - timedelta(days=10 - version),
    )


def _trade(tenant_id: int, ticker: str, thesis_version_id: int | None, key: str) -> PaperTrade:
    return PaperTrade(
        tenant_id=tenant_id, proposal_key=key, ticker=ticker, direction="long", horizon="short",
        thesis=f"tesis {key}", conviction=Decimal("0.5"), proposed_entry=Decimal("100"),
        stop=Decimal("90"), target=Decimal("120"), quantity=Decimal("1"),
        inference_basis="Inferencia: prueba", status="pending", thesis_version_id=thesis_version_id,
    )


def test_dca_policy_is_per_tenant(env):
    call = env["call"]
    saved = call("a", "PUT", "/api/settings/dca", {"up_min_level": 4, "down_max_level": 0})
    assert saved.status_code == 200, saved.text
    b = call("b", "GET", "/api/settings/dca").json()
    assert (b["configured"], b["up_min_level"], b["down_max_level"]) == (False, 3, 1)
    assert call("b", "PUT", "/api/settings/dca", {"up_min_level": 1, "down_max_level": 2}).status_code == 200
    a = call("a", "GET", "/api/settings/dca").json()
    assert (a["configured"], a["up_min_level"], a["down_max_level"]) == (True, 4, 0)


def test_savings_projection_never_uses_another_tenants_plan(env):
    call = env["call"]
    plan = {"monthly_contribution": 777, "start_date": "2026-01-01", "horizon_years": 12}
    saved = call("a", "PUT", "/api/plan", plan)
    assert saved.status_code in (200, 201), saved.text
    a = call("a", "GET", "/api/plan/savings-projection")
    b = call("b", "GET", "/api/plan/savings-projection")
    assert a.status_code == 200, a.text
    assert b.status_code < 500, b.text
    assert "777" in a.text
    assert "777" not in b.text


def test_attention_thesis_inbox_is_per_tenant(env):
    tid_a, tid_b = env["tenant_id"]("a"), env["tenant_id"]("b")
    cid, ticker = env["company_id"], env["ticker"]
    # Los dos vigilan la misma empresa; solo A tiene un cambio de tesis sin revisar.
    _write(tid_b, WatchItem(tenant_id=tid_b, symbol=ticker))
    (change_id,) = _write(tid_a, ThesisChange(tenant_id=tid_a, company_id=cid, summary="Cambio privado de A",
                                              created_at=NOW))
    _write(tid_a, WatchItem(tenant_id=tid_a, symbol=ticker),
           ResearchReview(tenant_id=tid_a, company_id=cid, thesis_change_id=change_id, status="open",
                          review_type="thesis", title="Revisar"))
    a = env["call"]("a", "GET", "/api/watchlist/attention-thesis")
    b = env["call"]("b", "GET", "/api/watchlist/attention-thesis")
    assert a.status_code == b.status_code == 200, (a.text, b.text)
    assert "Cambio privado de A" in a.text
    assert "Cambio privado de A" not in b.text
    assert b.json()["items"] == []


def test_manual_dca_run_status_is_per_tenant(env):
    tid_a = env["tenant_id"]("a")
    (run_id,) = _write(tid_a, DcaEvaluationRun(tenant_id=tid_a, trigger="manual", status="queued",
                                               started_at=datetime.now(UTC),
                                               detail={"requested_symbols": ["AAA"], "pending_remaining": 1}))
    a = env["call"]("a", "GET", f"/api/watchlist/dca-signals/manual-runs/{run_id}")
    b = env["call"]("b", "GET", f"/api/watchlist/dca-signals/manual-runs/{run_id}")
    assert a.status_code == 200, a.text
    assert 400 <= b.status_code < 500, b.text
    assert "AAA" not in b.text


def test_paper_proposals_by_ticker_and_thesis_anchor_are_per_tenant(env):
    tid_a, tid_b = env["tenant_id"]("a"), env["tenant_id"]("b")
    cid, ticker = env["company_id"], env["ticker"]
    a_versions = _write(tid_a, *(_thesis(tid_a, cid, v, f"Tesis A v{v}") for v in (1, 2, 3)))
    (b_v1,) = _write(tid_b, _thesis(tid_b, cid, 1, "Tesis B v1"))
    _write(tid_a, _trade(tid_a, ticker, a_versions[0], f"a-{ticker}"))
    _write(tid_b, _trade(tid_b, ticker, b_v1, f"b-{ticker}"))
    b = env["call"]("b", "GET", "/api/paper-trading/proposals", params={"ticker": ticker})
    assert b.status_code == 200, b.text
    rows = b.json()
    assert [row["proposal_key"] for row in rows] == [f"b-{ticker}"]
    # La versión más reciente de A (v3) no puede marcar como superada la tesis de B.
    assert rows[0]["thesis_anchor"]["latest_version"] == 1
    assert rows[0]["thesis_anchor"]["superseded"] is False
    a = env["call"]("a", "GET", "/api/paper-trading/proposals", params={"ticker": ticker}).json()
    assert [row["proposal_key"] for row in a] == [f"a-{ticker}"]
    assert a[0]["thesis_anchor"]["latest_version"] == 3


@pytest.mark.parametrize("suffix", ["latest", "versions", "history", "memo.md"])
def test_thesis_reads_never_show_another_tenants_thesis(env, suffix):
    tid_a = env["tenant_id"]("a")
    env["tenant_id"]("b")
    _write(tid_a, _thesis(tid_a, env["company_id"], 1, "Resumen confidencial de A"))
    path = f"/api/thesis/{env['ticker']}/{suffix}"
    a = env["call"]("a", "GET", path)
    b = env["call"]("b", "GET", path)
    assert a.status_code < 500 and b.status_code < 500, (a.text[:300], b.text[:300])
    assert "confidencial de A" not in b.text


def test_regenerate_tax_report_only_touches_own_tenant(env):
    call = env["call"]
    ticker = env["ticker"]
    for kind, day, price in (("buy", "2025-01-10", 10), ("sell", "2025-06-10", 30)):
        created = call("a", "POST", "/api/portfolio/transactions", {
            "ticker": ticker, "action": kind, "quantity": 10, "price": price,
            "currency": "EUR", "trade_date": day,
        })
        assert created.status_code in (200, 201), created.text
    a = call("a", "POST", "/api/taxes/report/2025/regenerate")
    b = call("b", "POST", "/api/taxes/report/2025/regenerate")
    assert a.status_code == 200, a.text
    assert b.status_code == 200, b.text
    assert ticker in a.text
    assert ticker not in b.text
    again = call("a", "GET", "/api/taxes/report/2025")
    assert again.status_code == 200 and ticker in again.text
