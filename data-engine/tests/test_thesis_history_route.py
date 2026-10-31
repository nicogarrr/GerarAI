"""GET /api/thesis/{ticker}/history con response_model.

Forma medida contra la ruta: envelope de 5 claves; item de 9 claves; diff
null sin version anterior, y la rama derivada (derived_thesis_diff) lleva
derived=true que la persistida OMITE: exclude_unset + test de ausencia.
Servicio real sobre SQLite, sin mock.
"""
from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import Company, Tenant, ThesisVersion
from tests.auth_helpers import auth_settings, signed_request

SECRET = "thesis-history-secret-"


def _client(monkeypatch) -> tuple[TestClient, str, str]:
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET),
    )
    init_db()
    tenant_ext = f"thesis-history-{uuid4().hex[:8]}"
    db = SessionLocal()
    db.add(Tenant(external_id=tenant_ext, name="Thesis history test"))
    db.commit()
    db.close()
    return TestClient(main.app), tenant_ext, "thesis-history-user"


def _tenant_pk(tenant_ext: str) -> int:
    db = SessionLocal()
    tenant = db.query(Tenant).filter(Tenant.external_id == tenant_ext).one()
    db.close()
    return tenant.id


def _seed_company_with_versions(tenant_ext: str) -> str:
    tenant_pk = _tenant_pk(tenant_ext)
    db = SessionLocal()
    # Ticker único por corrida: la sqlite del suite es compartida entre
    # workers y un «ACME» fijo commiteado aqui rompia el INSERT de otros
    # tests (UNIQUE companies.ticker en test_watchlist_monitor_route).
    ticker = f"TH{uuid4().hex[:8].upper()}"
    company = Company(ticker=ticker, name="Acme", exchange="NYSE", currency="USD",
                      company_type="operating", valuation_model="unassigned")
    db.add(company)
    db.flush()
    for version in (1, 2):
        db.add(ThesisVersion(
            tenant_id=tenant_pk, company_id=company.id, version=version,
            status="published", thesis_markdown="t", executive_summary="e",
            rating="buy" if version == 2 else "watch",
        ))
    db.commit()
    db.close()
    return ticker


def test_history_unknown_ticker_404(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)

    res = signed_request(client, SECRET, tenant, user, "GET", "/api/thesis/NOPE/history")

    assert res.status_code == 404


def test_history_envelope_and_derived_diff(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)
    ticker = _seed_company_with_versions(tenant)

    res = signed_request(client, SECRET, tenant, user, "GET", f"/api/thesis/{ticker}/history")

    assert res.status_code == 200, res.text
    payload = res.json()
    assert set(payload) == {"ticker", "count", "history", "data_as_of", "provenance"}
    assert payload["ticker"] == ticker
    assert payload["count"] == 2
    assert set(payload["provenance"]) == {
        "source", "source_kind", "source_url", "fetched_at", "coverage", "note",
    }
    v2, v1 = payload["history"]
    assert set(v2) == {
        "id", "version", "status", "rating", "red_team_score",
        "data_confidence_score", "created_at", "updated_at", "diff",
    }
    # Rama derivada: 5 claves con derived=true.
    assert set(v2["diff"]) == {
        "change_summary", "affected_assumptions", "rating_changed", "created_at", "derived",
    }
    assert v2["diff"]["derived"] is True
    assert v2["diff"]["rating_changed"] is True
    # Primera version: sin anterior, diff null.
    assert v1["diff"] is None
