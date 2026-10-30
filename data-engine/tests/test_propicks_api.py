"""ProPicks funnel API: signed run creation, listing and detail."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import (
    CalculatedMetric,
    Company,
    FinancialFact,
    ProPickCandidate,
    ProPickRun,
    Tenant,
)

SECRET = "propicks-api-test-secret-at-least-32-chars"

from tests.auth_helpers import auth_settings, signed_request


@pytest.fixture
def required_auth(monkeypatch):
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET),
    )


def _seed_company(db, tenant_id: int, ticker: str, roic: str, cfroi: str) -> Company:
    company = Company(
        ticker=ticker,
        name=f"{ticker} Co",
        exchange="TEST",
        currency="USD",
        sector="Industrials",
        industry="Test",
        company_type="standard",
        valuation_model="standard_dcf",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.flush()
    metrics = {
        "roic": roic,
        "cfroi_approx": cfroi,
        "wacc": "0.08",
        "fcf_margin_5y": "0.12",
        "owner_earnings_5y": "100",
        "roe_5y": "0.18",
        "net_margin_5y": "0.15",
        "roa_5y": "0.10",
        "capex_to_da_5y": "1.0",
        "quality_moat_score_v2": "0.7",
        "net_debt_to_ebitda": "1.0",
        "fcf_conversion": "0.9",
    }
    for metric, value in metrics.items():
        db.add(
            CalculatedMetric(
                company_id=company.id,
                metric=metric,
                value=Decimal(value),
                unit="decimal",
                period="FY2025",
                fiscal_year=2025,
                status="ok",
                definition_version="test-v1",
                formula=metric,
                source_fact_ids=[],
                calculation_trace={},
                confidence=Decimal("0.9"),
                tenant_id=tenant_id,
            )
        )
    for year in range(2021, 2026):
        for metric, value in (("net_income", "100"), ("revenue", str(900 + year))):
            db.add(
                FinancialFact(
                    company_id=company.id,
                    metric=metric,
                    value=Decimal(value),
                    unit="USD",
                    period=f"FY{year}",
                    fiscal_year=year,
                    fiscal_quarter="FY",
                    source_type="sec_filing",
                    confidence=Decimal("0.95"),
                    tenant_id=tenant_id,
                )
            )
    return company


def test_propicks_run_endpoints(required_auth):
    init_db()
    suffix = uuid4().hex[:8]
    tenant_ext = f"propicks-{suffix}"
    db = SessionLocal()
    tenant = Tenant(external_id=tenant_ext, name="ProPicks test")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    good = _seed_company(db, tenant.id, f"GOOD{suffix[:4]}", "0.20", "0.16")
    bad = _seed_company(db, tenant.id, f"BADD{suffix[:4]}", "0.01", "0.01")
    db.commit()
    good_id, bad_id = good.id, bad.id
    db.close()

    client = TestClient(main.app)
    user = "propicks-test-user"

    created = signed_request(client, SECRET, tenant_ext, user, "POST", "/api/propicks/runs")
    assert created.status_code == 201, created.text
    run = created.json()
    # The test app DB is shared: other suites' companies may exist.
    assert run["universe_size"] >= 2

    listed = signed_request(client, SECRET, tenant_ext, user, "GET", "/api/propicks/runs")
    assert listed.status_code == 200
    assert any(r["id"] == run["id"] for r in listed.json())

    detail = signed_request(client, SECRET, tenant_ext, user, "GET", f"/api/propicks/runs/{run['id']}")
    assert detail.status_code == 200
    body = detail.json()
    ours = [c for c in body["candidates"] if c["company_id"] == good_id]
    assert len(ours) == 1
    winner = ours[0]
    assert winner["rank"] and winner["rank"] >= 1
    assert winner["coverage"]["roic"] == "ok"
    assert all(c["company_id"] != bad_id for c in body["candidates"])

    full = signed_request(
        client, SECRET, tenant_ext, user, "GET", f"/api/propicks/runs/{run['id']}",
        params={"only_passed": "false"},
    )
    assert full.status_code == 200
    full_ids = {c["company_id"] for c in full.json()["candidates"]}
    assert {good_id, bad_id} <= full_ids

    missing = signed_request(client, SECRET, tenant_ext, user, "GET", "/api/propicks/runs/999999999")
    assert missing.status_code == 404

    unsigned = TestClient(main.app).get("/api/propicks/runs")
    assert unsigned.status_code == 401

    db = SessionLocal()
    db.execute(delete(ProPickCandidate).where(ProPickCandidate.run_id == run["id"]))
    db.execute(delete(ProPickRun).where(ProPickRun.id == run["id"]))
    for cid in (good_id, bad_id):
        db.execute(delete(CalculatedMetric).where(CalculatedMetric.company_id == cid))
        db.execute(delete(FinancialFact).where(FinancialFact.company_id == cid))
        db.execute(delete(Company).where(Company.id == cid))
    db.execute(delete(Tenant).where(Tenant.id == tenant.id))
    db.commit()
    db.close()


def test_propicks_run_detail_ordering(required_auth):
    """Orden del detalle del run: declarado y estable en los dos motores.

    Regresión: con only_passed=false, Postgres (NULL primero en DESC) ponía a
    los descartados por el embudo (score NULL) por ENCIMA de los aptos fuera
    del top_n, y sin desempate las filas con rank y score NULL salían en el
    orden que devolviera el motor, inestable entre llamadas. Contrato:
    rankeados por rank asc, luego aptos sin rank por score desc, luego
    descartados, con ticker como desempate final.
    """
    init_db()
    suffix = uuid4().hex[:8]
    tenant_ext = f"propicks-order-{suffix}"
    db = SessionLocal()
    tenant = Tenant(external_id=tenant_ext, name="ProPicks ordering test")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    good_a = _seed_company(db, tenant.id, f"ORDA{suffix[:4]}", "0.20", "0.16")
    good_b = _seed_company(db, tenant.id, f"ORDB{suffix[:4]}", "0.19", "0.15")
    bad = _seed_company(db, tenant.id, f"ORDBAD{suffix[:2]}", "0.01", "0.01")
    db.commit()
    ids = {good_a.id, good_b.id, bad.id}
    db.close()

    client = TestClient(main.app)
    user = "propicks-order-user"
    # top_n=1: solo un apto con rank; el otro queda apto sin rank (score
    # presente) y el descartado sin rank ni score.
    created = signed_request(
        client, SECRET, tenant_ext, user, "POST", "/api/propicks/runs",
        params={"top_n": 1},
    )
    assert created.status_code == 201, created.text
    run_id = created.json()["id"]

    detail = signed_request(
        client, SECRET, tenant_ext, user, "GET", f"/api/propicks/runs/{run_id}",
        params={"only_passed": "false"},
    )
    assert detail.status_code == 200
    candidates = detail.json()["candidates"]
    ours = [c for c in candidates if c["company_id"] in ids]
    assert len(ours) == 3
    # La BD del test es compartida: otras suites pueden dejar empresas que
    # también pasan el embudo, así que no se exige qué empresa lleva rank.
    passed = [c for c in ours if c["passed"]]
    not_passed = [c for c in ours if not c["passed"]]
    assert len(passed) == 2 and len(not_passed) == 1
    assert all(c["score"] is not None for c in passed)
    assert not_passed[0]["score"] is None
    # Los aptos (con o sin rank) van ANTES que el descartado (nulls_last
    # declarado); sin la corrección, Postgres lo ponía por encima.
    for c in passed:
        assert candidates.index(c) < candidates.index(not_passed[0])

    def order_key(c):
        return (
            c["rank"] is None,
            c["rank"] if c["rank"] is not None else 0,
            c["score"] is None,
            -(c["score"] or 0.0),
            c["ticker"],
        )

    keys = [order_key(c) for c in candidates]
    assert keys == sorted(keys), "el detalle del run no sale en el orden declarado"

    db = SessionLocal()
    db.execute(delete(ProPickCandidate).where(ProPickCandidate.run_id == run_id))
    db.execute(delete(ProPickRun).where(ProPickRun.id == run_id))
    for cid in ids:
        db.execute(delete(CalculatedMetric).where(CalculatedMetric.company_id == cid))
        db.execute(delete(FinancialFact).where(FinancialFact.company_id == cid))
        db.execute(delete(Company).where(Company.id == cid))
    db.execute(delete(Tenant).where(Tenant.id == tenant.id))
    db.commit()
    db.close()


def test_propicks_run_detail_prices(required_auth):
    """Detalle del run: current_price/price_as_of desde market_prices (None honesto sin precio)."""
    from datetime import date

    from app.models import MarketPrice

    init_db()
    suffix = uuid4().hex[:8]
    tenant_ext = f"propicks-price-{suffix}"
    db = SessionLocal()
    tenant = Tenant(external_id=tenant_ext, name="ProPicks price test")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    priced = _seed_company(db, tenant.id, f"PRIC{suffix[:4]}", "0.20", "0.16")
    unpriced = _seed_company(db, tenant.id, f"NOPR{suffix[:4]}", "0.19", "0.15")
    db.add(
        MarketPrice(
            company_id=priced.id,
            date=date(2026, 9, 24),
            open=123.45,
            high=123.45,
            low=123.45,
            close=123.45,
        )
    )
    db.commit()
    priced_id, unpriced_id = priced.id, unpriced.id
    db.close()

    client = TestClient(main.app)
    user = "propicks-price-user"
    created = signed_request(client, SECRET, tenant_ext, user, "POST", "/api/propicks/runs")
    assert created.status_code == 201, created.text
    run_id = created.json()["id"]

    detail = signed_request(client, SECRET, tenant_ext, user, "GET", f"/api/propicks/runs/{run_id}")
    assert detail.status_code == 200
    by_company = {c["company_id"]: c for c in detail.json()["candidates"]}
    assert by_company[priced_id]["current_price"] == 123.45
    assert by_company[priced_id]["price_as_of"] == "2026-09-24"
    assert by_company[unpriced_id]["current_price"] is None
    assert by_company[unpriced_id]["price_as_of"] is None
