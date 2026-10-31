"""GET /api/propicks/radar/opportunities: paginación, filtros y cobertura."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import propicks_radar as radar_module
from app.core.database import Base, get_db
from app.models import (CalculatedMetric, Company, FinancialFact, MarketPrice,
                        ProPickCandidate, ProPickRun, Tenant, WatchItem)
from app.services.propicks_radar_store import save_snapshot

NOW = datetime(2026, 10, 30, 22, 0, tzinfo=UTC)


def _payload(level: int, *, status: str = "ok") -> dict:
    if status != "ok":
        return {"status": status, "reason": "stale"}
    current = {"level": level, "status": "forming", "signal_date": "2026-10-29",
               "close": 91.5, "zone": {"label": f"{level}X DCA"}}
    return {"status": "ok", "formula_version": "nico-v1", "price_verified": True,
            "price_date": "2026-10-29", "source": "yfinance",
            "current": current, "confirmed": {"level": 1, "period": "2026-09"},
            "clear_price_signal": level == 4}


@pytest.fixture
def db_session(monkeypatch):
    # Fecha fija: la vigencia de un snapshot (regla >3 días) depende de
    # date.today(); sin esto el test se rompería al correrlo otra semana.
    class _FixedDate(date):
        @classmethod
        def today(cls) -> date:
            return date(2026, 10, 31)

    monkeypatch.setattr(radar_module, "date", _FixedDate)
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(engine)()
    db.add(Tenant(id=1, external_id="t"))
    # 25 empresas ok (niveles variados) + 1 inválida + 1 sin snapshot.
    for cid in range(1, 27):
        db.add(Company(id=cid, ticker=f"T{cid:02d}", name=f"Co {cid}", exchange="NASDAQ",
                       currency="USD", sector="Technology" if cid % 2 else "Energy",
                       industry="Test", company_type="large_cap", valuation_model="dcf"))
    db.add(Company(id=99, ticker="NOSNAP", name="Sin snapshot", exchange="NASDAQ",
                   currency="USD", sector="Technology", industry="Test",
                   company_type="large_cap", valuation_model="dcf"))
    # El universo = empresas con al menos un precio persistido (27 aquí).
    for cid in list(range(1, 27)) + [99]:
        db.add(MarketPrice(company_id=cid, date=NOW.date(), open=1, high=1, low=1,
                           close=1, adj_close=1, volume=1, quote_currency="USD", source="test"))
    db.commit()
    for cid in range(1, 26):
        save_snapshot(db, cid, _payload(4 if cid <= 3 else (3 if cid <= 10 else 1)), now=NOW)
    save_snapshot(db, 26, _payload(0, status="invalid"), now=NOW)
    db.add(WatchItem(tenant_id=1, symbol="T01"))
    db.commit()

    return db


@pytest.fixture
def client(db_session):
    app = FastAPI()
    app.include_router(radar_module.router, prefix="/api/propicks")

    def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    return TestClient(app)


def test_pagination_20_per_page_and_counts(client):
    page1 = client.get("/api/propicks/radar/opportunities").json()
    assert page1["page_size"] == 20
    assert len(page1["items"]) == 20
    assert page1["total"] == 25
    assert page1["has_more"] is True
    page2 = client.get("/api/propicks/radar/opportunities", params={"page": 2}).json()
    assert len(page2["items"]) == 5
    assert page2["has_more"] is False
    # Nivel 4 primero (orden por nivel desc, ticker).
    assert [i["level"] for i in page1["items"][:3]] == [4, 4, 4]
    assert page1["counts_by_level"] == {"4": 3, "3": 7, "1": 15}
    # Cobertura honesta: la inválida cuenta aparte; NOSNAP no está evaluada.
    assert page1["coverage"] == {"universe": 27, "evaluated": 26, "ok": 25, "invalid": 1,
                                        "stale": 0}
    row = page1["items"][0]
    assert row["formula_version"] == "nico-v1"
    assert row["status"] == "forming"
    assert row["confirmed_level"] == 1
    assert row["signal_date"] == "2026-10-29"
    assert row["source"] == "yfinance"
    assert row["clear_price_signal"] is True
    assert row["scan_date"] == "2026-10-30"


def test_level_and_sector_filters(client):
    only4 = client.get("/api/propicks/radar/opportunities", params={"level": 4}).json()
    assert only4["total"] == 3
    assert {i["level"] for i in only4["items"]} == {4}
    energy = client.get("/api/propicks/radar/opportunities", params={"sector": "Energy"}).json()
    assert energy["total"] == 12
    assert {i["sector"] for i in energy["items"]} == {"Energy"}
    assert set(client.get("/api/propicks/radar/opportunities").json()["sectors"]) == {"Energy", "Technology"}
    # La cobertura es global: no baja al filtrar por sector.
    assert energy["coverage"]["ok"] == 25
    assert energy["total"] == 12


def test_outside_tracked_excludes_watchlist(client):
    # Sin contexto de tenant en dev, WatchItem(tenant_id=1) es visible (legacy
    # unscoped): el filtro excluye T01 y no inventa pertenencia.
    res = client.get("/api/propicks/radar/opportunities", params={"outside_tracked": True}).json()
    assert res["total"] == 24
    assert "T01" not in {i["ticker"] for i in res["items"]}
    assert res["counts_by_level"]["4"] == 2


def test_post_scan_enqueues_actor(client, monkeypatch):
    from app.workers import dramatiq_app

    sent = {}

    class _Msg:
        message_id = "msg-1"

    def _send(**kwargs):
        sent.update(kwargs)
        return _Msg()

    monkeypatch.setattr(dramatiq_app.propicks_radar_scan, "send", _send)
    res = client.post("/api/propicks/radar/scan")
    assert res.status_code == 202
    assert res.json() == {"status": "queued", "broker_message_id": "msg-1"}


def test_actor_is_registered_on_computed_queue():
    import dramatiq

    from app.workers.dramatiq_app import propicks_radar_scan

    assert isinstance(propicks_radar_scan, dramatiq.Actor)
    assert propicks_radar_scan.queue_name == "computed"
    # Radar sin outbox: no comparte la cola de alertas del evaluador DCA.
    assert propicks_radar_scan.queue_name != "alerts"


def test_stale_scan_is_not_an_opportunity(client, db_session):
    # Scan antiguo y NINGUNA corrida nueva: el snapshot viejo deja de ser
    # vigente (cuenta en coverage.stale, no aparece como oportunidad).
    save_snapshot(db_session, 99, _payload(4), now=datetime(2026, 10, 10, 22, 0, tzinfo=UTC))
    db_session.commit()
    res = client.get("/api/propicks/radar/opportunities").json()
    assert "NOSNAP" not in {i["ticker"] for i in res["items"]}
    assert res["total"] == 25
    assert res["coverage"] == {"universe": 27, "evaluated": 27, "ok": 25, "invalid": 1,
                               "stale": 1}


def test_snapshot_at_three_days_is_still_fresh(client, db_session):
    # Frontera de la regla (>3 días): a los 3 días exactos sigue vigente.
    save_snapshot(db_session, 99, _payload(2), now=datetime(2026, 10, 28, 22, 0, tzinfo=UTC))
    db_session.commit()
    res = client.get("/api/propicks/radar/opportunities").json()
    assert "NOSNAP" in {i["ticker"] for i in res["items"]}
    assert res["coverage"]["stale"] == 0


def test_quality_clear_filter(client, db_session):
    # QUAL tiene todos los inputs quality-v1; el resto no (nunca pasan por defecto).
    db_session.add(Company(id=50, ticker="QUAL", name="Quality Co", exchange="NASDAQ",
                           currency="USD", sector="Technology", industry="Test",
                           company_type="large_cap", valuation_model="dcf"))
    day = date(2026, 10, 30)
    for i in range(20):
        db_session.add(MarketPrice(company_id=50, date=day - timedelta(days=i), open=100,
                                   high=100, low=100, close=100, adj_close=100,
                                   volume=200_000, quote_currency="USD", source="test"))
    run = ProPickRun(tenant_id=1, as_of=datetime(2026, 10, 30, tzinfo=UTC),
                     status="completed", funnel_version="v1")
    db_session.add(run)
    db_session.flush()
    db_session.add(ProPickCandidate(tenant_id=1, run_id=run.id, company_id=50, passed=True))
    db_session.add(CalculatedMetric(tenant_id=1, company_id=50, metric="net_debt_to_ebitda",
                                    value=1.5, period="2025-FY", formula="test"))
    db_session.add(CalculatedMetric(tenant_id=1, company_id=50, metric="market_cap",
                                    value=2_000_000_000, period="2026-10-30", formula="test"))
    db_session.add(FinancialFact(tenant_id=1, company_id=50, metric="free_cash_flow",
                                 value=120, unit="USD", period="2025-FY", fiscal_year=2025,
                                 filed=date(2026, 10, 15)))
    db_session.add(FinancialFact(tenant_id=1, company_id=50, metric="free_cash_flow",
                                 value=100, unit="USD", period="2024-FY", fiscal_year=2024,
                                 filed=date(2025, 3, 1)))
    db_session.commit()
    save_snapshot(db_session, 50, _payload(4), now=NOW)
    db_session.commit()

    res = client.get("/api/propicks/radar/opportunities").json()
    qual = next(i for i in res["items"] if i["ticker"] == "QUAL")
    assert qual["quality"]["passed"] is True
    other = next(i for i in res["items"] if i["ticker"] == "T02")
    assert other["quality"]["passed"] is False

    clear = client.get("/api/propicks/radar/opportunities", params={"quality": "clear"}).json()
    assert {i["ticker"] for i in clear["items"]} == {"QUAL"}
    assert clear["total"] == 1

    assert client.get("/api/propicks/radar/opportunities",
                      params={"quality": "bogus"}).status_code == 422
