"""API de lectura de notas de analista: por tenant, en el orden del ranking de
casas de #4543 y con las de otras casas aparte. Sin red (ranking stub)."""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import main
from app.api.routes import analyst_notes as route
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import Company, Tenant
from app.services import analyst_history_service as ahs
from app.services.analyst_note_service import AnalystNoteInput, analyst_note_service
from tests.auth_helpers import auth_settings, signed_request
from tests.test_cross_tenant_probes import _no_network

SECRET = "analyst-notes-secret-with-32-chars-ok!!"


def _score(firm: str, err: float) -> ahs.FirmScore:
    return ahs.FirmScore(
        firm=firm,
        samples=8,
        median_abs_error_pct=err,
        median_bias_pct=1.0,
        direction_hit_rate=0.7,
        relative_error=-err,
        peer_scored_samples=8,
        last_date="2026-10-01",
        last_target=250.0,
    )


def _history(symbol: str, top: list[ahs.FirmScore]) -> ahs.AnalystHistory:
    return ahs.AnalystHistory(
        symbol=symbol,
        status="available",
        fetched_at=0,
        best_horizon="12m",
        horizons=[
            ahs.HorizonSummary(horizon="6m", months=6, matured_targets=3, top=[_score("Other", 1)]),
            ahs.HorizonSummary(horizon="12m", months=12, matured_targets=30, top=top),
        ],
    )


@pytest.fixture(autouse=True)
def mount_unregistered_route():
    # API read model is staged first; production registration follows separately.
    if any(getattr(item, "path", "") == "/api/companies/{ticker}/analyst-notes" for item in main.app.routes):
        yield
        return
    original = list(main.app.router.routes)
    from app.api.router import api_router
    from fastapi import APIRouter

    staging = APIRouter(dependencies=api_router.dependencies)
    staging.include_router(route.router, prefix="/companies", tags=["companies"])
    main.app.include_router(staging, prefix="/api")
    yield
    main.app.router.routes[:] = original
    main.app.openapi_schema = None


@pytest.fixture()
def env(monkeypatch):
    _no_network(monkeypatch)
    init_db()
    monkeypatch.setattr(
        auth_module, "get_settings", lambda: auth_settings(strict=True, secret=SECRET, app_env="test")
    )
    suffix = uuid4().hex[:8]
    ticker = f"AN{suffix[:4].upper()}"
    tenants: dict[str, int] = {}
    with SessionLocal() as db:
        db.add(
            Company(
                ticker=ticker,
                name=f"Empresa {ticker}",
                exchange="NASDAQ",
                currency="USD",
                company_type="operating",
                valuation_model="standard_dcf",
            )
        )
        for who in ("a", "b"):
            tenant = Tenant(external_id=f"{who}-{suffix}", name=who)
            db.add(tenant)
            db.flush()
            tenants[who] = tenant.id

        def note(tenant_id, firm, day, pt, **kw):
            analyst_note_service.upsert(
                db,
                tenant_id,
                AnalystNoteInput(
                    ticker=ticker,
                    firm=firm,
                    note_date=day,
                    action="maintain",
                    source_type="news",
                    pt_new=pt,
                    price_at_note=200,
                    quote=f"{firm} says buy",
                    source_url=f"https://n.example.com/{firm.replace(' ', '-')}",
                    **kw,
                ),
            )

        a = tenants["a"]
        note(a, "Barclays", date(2026, 11, 3), 273, key_arguments=["aceleración comercial"])
        note(a, "Barclays", date(2026, 8, 3), 265)
        note(a, "BofA Securities", date(2026, 11, 4), 255, analyst="Mariana Pérez Mora")
        note(a, "Jefferies", date(2026, 11, 2), 70)
        analyst_note_service.upsert(
            db,
            a,
            AnalystNoteInput(
                ticker=ticker,
                firm="Some Desk",
                note_date=date(2026, 11, 1),
                action="upgrade",
                source_type="social",
                quote="hearing an upgrade",
                source_url="https://x.com/a/status/1",
            ),
        )
        note(tenants["b"], "Barclays", date(2026, 11, 3), 999)
        db.commit()
    histories = {
        "value": _history(
            ticker, [_score("BofA Securities", 10), _score("Barclays", 12), _score("Morgan Stanley", 13)]
        )
    }

    async def fake_get(symbol: str, **_kw):
        return histories["value"]

    monkeypatch.setattr(ahs.analyst_history_service, "get", fake_get)
    client = TestClient(main.app)

    def call(who: str, params: dict | None = None):
        path = f"/api/companies/{ticker}/analyst-notes"
        return signed_request(client, SECRET, f"{who}-{suffix}", f"user-{who}", "GET", path, params=params)

    return {"call": call, "client": client, "ticker": ticker, "histories": histories}


def test_sin_firma_401(env):
    assert env["client"].get(f"/api/companies/{env['ticker']}/analyst-notes").status_code == 401


def test_notas_de_las_mejores_casas_en_orden_del_ranking(env):
    res = env["call"]("a")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "available" and body["ranking_status"] == "ranked"
    assert body["ranking_horizon"] == "12m"
    assert [f["firm"] for f in body["ranked_firms"]] == ["BofA Securities", "Barclays", "Morgan Stanley"]
    notes = body["notes"]
    assert [(n["firm"], n["firm_rank"], n["note_date"]) for n in notes] == [
        ("BofA Securities", 1, "2026-11-04"),
        ("Barclays", 2, "2026-11-03"),
    ]
    bofa = notes[0]
    assert bofa["analyst"] == "Mariana Pérez Mora" and bofa["pt_new"] == 255.0
    assert bofa["upside_pct"] == pytest.approx(27.5)
    assert (
        bofa["verification"] == "verificado" and bofa["source_url"] == "https://n.example.com/BofA-Securities"
    )
    others = body["other_notes"]
    assert [(n["firm"], n["firm_rank"]) for n in others] == [("Jefferies", None), ("Some Desk", None)]
    assert others[1]["verification"] == "rumor_no_verificado" and others[1]["source_type"] == "social"


def test_per_firm_y_others(env):
    body = env["call"]("a", {"per_firm": 2, "others": 0}).json()
    assert [(n["firm"], n["note_date"]) for n in body["notes"]] == [
        ("BofA Securities", "2026-11-04"),
        ("Barclays", "2026-11-03"),
        ("Barclays", "2026-08-03"),
    ]
    assert body["other_notes"] == []
    assert env["call"]("a", {"per_firm": 9}).status_code == 422


def test_otro_tenant_no_ve_las_notas(env):
    body = env["call"]("b").json()
    assert [(n["firm"], n["pt_new"]) for n in body["notes"]] == [("Barclays", 999.0)]
    assert body["other_notes"] == []


def test_sin_ranking_salen_por_fecha(env):
    env["histories"]["value"] = ahs.AnalystHistory(
        symbol=env["ticker"], fetched_at=0, note="No se pudo consultar", note_code="fetch_failed"
    )
    body = env["call"]("a").json()
    assert body["ranking_status"] == "unranked" and body["ranked_firms"] == [] and body["notes"] == []
    assert body["ranking_note"] == "No se pudo consultar"
    assert [n["firm"] for n in body["other_notes"]] == [
        "BofA Securities",
        "Barclays",
        "Jefferies",
        "Some Desk",
        "Barclays",
    ]


def test_ticker_inexistente_404(env):
    path = "/api/companies/NOPE0000/analyst-notes"
    res = signed_request(env["client"], SECRET, "a-x", "user-a", "GET", path)
    assert res.status_code == 404


def test_sin_tenant_no_hay_notas():
    view = route.build_view(None, None, "PLTR", None, per_firm=1, others=5)  # type: ignore[arg-type]
    assert view.status == "no_tenant" and view.notes == [] and view.ranking_status == "unranked"
