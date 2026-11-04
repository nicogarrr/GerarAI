"""«Nuestro acierto»: valores razonables de GerarAI contra el precio real.

Servicio con versiones y precios sintéticos (sin lookahead: un precio
posterior al horizonte no cambia nada), idempotencia del job, estado
pendiente con la fecha del primer vencimiento y aislamiento entre tenants
del endpoint.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import Company, MarketPrice, Tenant, ThesisVersion
from app.models.thesis_realized_return import ThesisRealizedReturn
from app.services import thesis_track_record_service as svc
from app.services.thesis_track_record_service import PriceRow, score_version
from tests.auth_helpers import auth_settings, signed_request
from tests.test_cross_tenant_probes import _no_network

SECRET = "thesis-track-record-secret-with-32-chars!!"
ISSUE = date(2026, 1, 5)  # lunes


def _series(start: date, days: int, fn) -> list[PriceRow]:
    out = []
    for i in range(days):
        d = start + timedelta(days=i)
        if d.weekday() < 5:
            out.append(PriceRow(day=d, close=fn(i)))
    return out


# ------------------------------------------------------------------ función pura


def test_horizonte_vencido_error_direccion_y_toque():
    # 100 al emitir, sube linealmente a ~130 a los 6 meses; valor razonable 120.
    prices = _series(ISSUE, 400, lambda i: 100 + i * 30 / 181)
    out = score_version(issue=ISSUE, fair_value=120.0, stored_price=100.0, prices=prices,
                        today=date(2026, 7, 10))
    assert out["entry_status"] == "ok" and out["entry_price"] == 100.0
    h6, h12 = out["horizons"]
    assert h6["status"] == "matured" and h6["target_date"] == "2026-07-05"
    assert h6["price_date"] == "2026-07-06"  # domingo -> primer cierre del lunes
    assert h6["direction_hit"] is True
    assert h6["touched"] is True
    assert h6["signed_error"] < 0  # nos quedamos cortos: 120 frente a ~30% de subida
    assert h6["abs_error"] == pytest.approx(-h6["signed_error"])
    assert h12["status"] == "pending"


def test_sin_lookahead_un_precio_posterior_no_cambia_el_resultado():
    base = _series(ISSUE, 200, lambda i: 100 - i * 0.05)
    today = date(2026, 12, 31)
    a = score_version(issue=ISSUE, fair_value=150.0, stored_price=None, prices=base, today=today)
    # Después del cierre del horizonte de 6 meses el precio se dispara por
    # encima del valor razonable: el 6M ni lo ve (ni el toque ni el error).
    after = [PriceRow(day=date(2026, 7, 7) + timedelta(days=i), close=1000.0, high=1000.0) for i in range(60)]
    b = score_version(issue=ISSUE, fair_value=150.0, stored_price=None, prices=base + after, today=today)
    assert a["horizons"][0]["status"] == "matured"
    assert a["horizons"][0] == b["horizons"][0]
    assert b["horizons"][0]["touched"] is False
    assert b["horizons"][0]["direction_hit"] is False


def test_horizonte_no_vencido_queda_pendiente_aunque_haya_precios_futuros():
    prices = _series(ISSUE, 400, lambda i: 100 + i)
    out = score_version(issue=ISSUE, fair_value=120.0, stored_price=None, prices=prices,
                        today=date(2026, 7, 4))
    assert [h["status"] for h in out["horizons"]] == ["pending", "pending"]
    assert "price" not in out["horizons"][0]


def test_unidades_que_no_casan_no_se_puntuan():
    prices = _series(ISSUE, 400, lambda i: 100.0)
    out = score_version(issue=ISSUE, fair_value=120.0, stored_price=1.0, prices=prices,
                        today=date(2027, 3, 1))
    assert out["entry_status"] == "unit_mismatch"
    assert {h["status"] for h in out["horizons"]} == {"unit_mismatch"}


def test_sin_cierre_al_emitir_no_usa_uno_posterior():
    prices = _series(ISSUE + timedelta(days=20), 400, lambda i: 100.0)
    out = score_version(issue=ISSUE, fair_value=120.0, stored_price=None, prices=prices,
                        today=date(2027, 3, 1))
    assert out["entry_status"] == "no_entry_price"


def test_split_con_serie_ajustada_escala_el_valor_razonable():
    # Split 2:1 a mitad de ventana: close cae a la mitad, adj_close continuo.
    rows = []
    for p in _series(ISSUE, 200, lambda i: 100.0):
        post = p.day >= date(2026, 4, 1)
        rows.append(PriceRow(day=p.day, close=55.0 if post else 100.0, adj_close=55.0 if post else 50.0))
    out = score_version(issue=ISSUE, fair_value=105.0, stored_price=100.0, prices=rows, today=date(2026, 8, 1))
    h6 = out["horizons"][0]
    assert h6["price_basis"] == "adj_close"
    assert h6["realized_return"] == pytest.approx(0.10)
    assert h6["direction_hit"] is True and h6["touched"] is True


def test_mejor_horizonte_exige_muestras_y_prefiere_acierto():
    s = {"6M": {"samples": 5, "hit_rate": 0.6, "median_abs_error": 0.2},
         "12M": {"samples": 4, "hit_rate": 0.75, "median_abs_error": 0.3}}
    assert svc.best_horizon(s) == ("12M", "hit_rate")
    s["12M"]["samples"] = 2
    assert svc.best_horizon(s) == ("6M", "hit_rate")
    s["6M"]["samples"] = 1
    assert svc.best_horizon(s) == (None, "insufficient_samples")


# ------------------------------------------------------------------ job con BD


def _company(db, ticker: str) -> Company:
    company = Company(ticker=ticker, name=f"Empresa {ticker}", exchange="NASDAQ", currency="USD",
                      sector="Test", industry="Test", company_type="standard", valuation_model="standard_dcf")
    db.add(company)
    db.flush()
    return company


def _version(company_id: int, tenant_id: int, issued: date, base: str, n: int = 1, status: str = "draft",
             price: str = "100") -> ThesisVersion:
    return ThesisVersion(
        company_id=company_id, tenant_id=tenant_id, version=n, status=status, thesis_markdown="t",
        executive_summary="s", base_value=Decimal(base), current_price=Decimal(price),
        created_at=datetime(issued.year, issued.month, issued.day, 15, tzinfo=UTC),
    )


def _prices(db, company_id: int, start: date, days: int, fn) -> None:
    for row in _series(start, days, fn):
        db.add(MarketPrice(company_id=company_id, date=row.day, close=Decimal(str(round(row.close, 4))),
                           source="test"))


def _tenant(db, label: str) -> int:
    tenant = Tenant(external_id=f"{label}-{uuid4().hex[:8]}", name=label, status="active")
    db.add(tenant)
    db.flush()
    return tenant.id


def test_job_rellena_es_idempotente_y_un_precio_posterior_no_reescribe():
    init_db()
    ticker = f"TR{uuid4().hex[:4].upper()}"
    with SessionLocal() as db:
        tenant_id = _tenant(db, "tr-job")
        company = _company(db, ticker)
        _prices(db, company.id, ISSUE, 220, lambda i: 100 + i * 0.1)
        db.add_all([
            _version(company.id, tenant_id, ISSUE, "130", 1),
            _version(company.id, tenant_id, ISSUE, "131", 2),  # mismo día: una sola muestra
            _version(company.id, tenant_id, ISSUE, "90", 3, status="insufficient_data"),
        ])
        db.commit()
        company_id = company.id

    def run(today: date) -> dict:
        with SessionLocal() as db:
            db.info["tenant_id"] = tenant_id
            return svc.refresh_track_record(db, today=today)

    first = run(date(2026, 7, 20))
    assert (first["versions"], first["created"]) == (2, 2)
    assert run(date(2026, 7, 21))["unchanged"] == 2
    with SessionLocal() as db:
        db.info["tenant_id"] = tenant_id
        rows = db.scalars(select(ThesisRealizedReturn).where(ThesisRealizedReturn.company_id == company_id)).all()
        assert {r.judgement_status for r in rows} == {"partial"}
        assert {r.outcome for r in rows} == {"hit"}
        before = [r.horizons[0] for r in rows]
        # Llega un cierre posterior al horizonte de 6 meses: nada cambia.
        row = db.scalar(select(MarketPrice).where(MarketPrice.company_id == company_id,
                                                  MarketPrice.date == date(2026, 7, 22)))
        assert row is not None
        row.close = Decimal("1")
        db.commit()
    assert run(date(2026, 7, 23))["unchanged"] == 2
    with SessionLocal() as db:
        db.info["tenant_id"] = tenant_id
        rows = db.scalars(select(ThesisRealizedReturn).where(ThesisRealizedReturn.company_id == company_id)).all()
        assert [r.horizons[0] for r in rows] == before
        assert {r.revision for r in rows} == {1}
        company = db.get(Company, company_id)
        assert company is not None
        payload = svc.company_track_record(db, company)
    assert payload["status"] == "ready"
    assert payload["horizons"]["6M"]["samples"] == 1  # dos versiones el mismo día = una muestra
    assert payload["horizons"]["6M"]["hit_rate"] == 1.0
    assert payload["first_maturity_date"] == "2026-07-05"


# ------------------------------------------------------------------ API


@pytest.fixture()
def env(monkeypatch):
    _no_network(monkeypatch)
    init_db()
    monkeypatch.setattr(auth_module, "get_settings",
                        lambda: auth_settings(strict=True, secret=SECRET, app_env="test"))
    from app.workers import dramatiq_app

    monkeypatch.setattr(dramatiq_app.broker, "enqueue", lambda message, delay=None: message)
    suffix = uuid4().hex[:8]
    client = TestClient(main.app)

    def call(tenant: str, path: str):
        return signed_request(client, SECRET, f"{tenant}-{suffix}", f"user-{tenant}-{suffix}", "GET", path)

    def tenant_id(tenant: str) -> int:
        assert call(tenant, "/api/thesis-track-record").status_code == 200
        with SessionLocal() as db:
            found = db.scalar(select(Tenant.id).where(Tenant.external_id == f"{tenant}-{suffix}"))
            assert found is not None
            return found

    return {"call": call, "tenant_id": tenant_id, "ticker": f"ZR{suffix[:4].upper()}"}


def test_api_aislada_por_tenant_y_estado_pendiente(env):
    call, ticker = env["call"], env["ticker"]
    a, b = env["tenant_id"]("a"), env["tenant_id"]("b")
    with SessionLocal() as db:
        company = _company(db, ticker)
        _prices(db, company.id, ISSUE, 220, lambda i: 100 + i * 0.1)
        db.add(_version(company.id, a, ISSUE, "130"))
        # B solo tiene una tesis reciente: pendiente, con su fecha de vencimiento.
        db.add(_version(company.id, b, date(2026, 6, 1), "80"))
        db.commit()
    with SessionLocal() as db:
        db.info["tenant_id"] = a
        svc.refresh_track_record(db, today=date(2026, 7, 20))
    with SessionLocal() as db:
        db.info["tenant_id"] = b
        svc.refresh_track_record(db, today=date(2026, 7, 20))

    ra = call("a", f"/api/companies/{ticker}/track-record")
    rb = call("b", f"/api/companies/{ticker}/track-record")
    assert ra.status_code == 200 and rb.status_code == 200
    ja, jb = ra.json(), rb.json()
    assert ja["status"] == "ready" and ja["horizons"]["6M"]["samples"] == 1
    assert ja["first_maturity_date"] == "2026-07-05"
    assert jb["status"] == "pending" and jb["horizons"]["6M"]["samples"] == 0
    assert jb["first_maturity_date"] == "2026-12-01"
    assert jb["versions_tracked"] == 1

    agg_a = call("a", "/api/thesis-track-record").json()
    agg_b = call("b", "/api/thesis-track-record").json()
    assert [t["ticker"] for t in agg_a["tickers"]] == [ticker]
    assert ticker not in [t["ticker"] for t in agg_b["tickers"]]
    assert agg_b["status"] == "pending"


def test_api_sin_tesis_no_data(env):
    call, ticker = env["call"], env["ticker"]
    env["tenant_id"]("c")
    with SessionLocal() as db:
        _company(db, ticker)
        db.commit()
    body = call("c", f"/api/companies/{ticker}/track-record").json()
    assert body["status"] == "no_data" and body["first_maturity_date"] is None
