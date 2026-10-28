"""Estrategia deep value: gates, score, frescura de metrica y contrato del endpoint."""
from datetime import date, timedelta
from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes import propicks as propicks_route
from app.core.database import Base, get_db
from app.models import CalculatedMetric, Tenant
from app.services.deep_value_service import STRATEGY_ID, find_deep_value
from app.services.valuation_metrics_service import (
    METRIC_PB,
    METRIC_VERSION,
    METRIC_YIELD,
    STATUS_DISAGREE,
    STATUS_OK,
)
from tests.test_propicks_prices import _company, _db

TODAY = date(2026, 10, 27)


def _metric(db, company, metric, value, period, status=STATUS_OK, trace=None):
    db.add(
        CalculatedMetric(
            tenant_id=db.info["tenant_id"],
            company_id=company.id,
            metric=metric,
            value=Decimal(str(value)),
            unit="decimal",
            period=period,
            fiscal_year=int(period[:4]),
            status=status,
            definition_version=METRIC_VERSION,
            formula="test",
            source_fact_ids=[],
            calculation_trace=trace or {},
        )
    )
    db.flush()


def _seed(db, ticker, pb, yld=None, period=TODAY.isoformat(), yield_status=STATUS_OK,
          pb_trace=None, y_trace=None):
    company = _company(ticker)
    db.add(company)
    db.flush()
    _metric(db, company, METRIC_PB, pb, period, trace=pb_trace or {
        "price_date": period, "fiscal_year": 2025, "equity_source": "SEC",
    })
    if yld is not None:
        _metric(db, company, METRIC_YIELD, yld, period, status=yield_status,
                trace=y_trace or {})
    return company


def test_pb_por_encima_del_umbral_excluido():
    db = _db()
    _seed(db, "CARA", pb="1.5")
    assert find_deep_value(db, pb_max=Decimal("1.0"), today=TODAY) == []
    rows = find_deep_value(db, pb_max=Decimal("2.0"), today=TODAY)
    assert [r.ticker for r in rows] == ["CARA"]


def test_yield_minimo_filtra_y_ausente_es_nd():
    db = _db()
    _seed(db, "SINY", pb="0.8")  # sin metrica de yield
    _seed(db, "CONY", pb="0.8", yld="0.06")
    rows = find_deep_value(db, pb_max=Decimal("1.0"), yield_min=Decimal("0.05"), today=TODAY)
    assert [r.ticker for r in rows] == ["CONY"]
    # yield_min=0: la sin yield entra con dividend_yield=None (N/D, no 0)
    rows = find_deep_value(db, pb_max=Decimal("1.0"), today=TODAY)
    by_t = {r.ticker: r for r in rows}
    assert by_t["SINY"].dividend_yield is None
    assert by_t["CONY"].dividend_yield == Decimal("0.06")


def test_metrica_vieja_no_se_sirve():
    db = _db()
    old = (TODAY - timedelta(days=10)).isoformat()
    _seed(db, "VIEJA", pb="0.5", period=old)
    assert find_deep_value(db, pb_max=Decimal("1.0"), today=TODAY) == []


def test_desacuerdo_y_extremo_se_propagan():
    db = _db()
    _seed(db, "DIS", pb="0.6", yld="0.30", yield_status=STATUS_DISAGREE,
          y_trace={"desacuerdo_fuentes": True, "yield_extremo_revisar": True,
                   "finnhub_yield_indicated": "0.20"})
    rows = find_deep_value(db, pb_max=Decimal("1.0"), today=TODAY)
    (row,) = rows
    assert row.desacuerdo_fuentes is True
    assert row.yield_extremo_revisar is True
    assert row.yield_status == STATUS_DISAGREE
    assert row.finnhub_yield_indicated == Decimal("0.20")  # la otra cifra, visible
    assert any("no oficial" in f for f in row.fuentes)
    assert "SEC" in row.fuentes


def test_score_ordena_mas_barato_y_mas_yield_primero():
    db = _db()
    _seed(db, "A", pb="0.9", yld="0.00")
    _seed(db, "B", pb="0.4", yld="0.08")
    rows = find_deep_value(db, pb_max=Decimal("1.0"), today=TODAY)
    assert [r.ticker for r in rows] == ["B", "A"]
    assert rows[0].score > rows[1].score


def test_limit_y_orden_estable():
    db = _db()
    for i in range(5):
        _seed(db, f"T{i}", pb="0.5", yld="0.05")
    rows = find_deep_value(db, pb_max=Decimal("1.0"), limit=2, today=TODAY)
    assert len(rows) == 2


def _db_mt():
    """SQLite en memoria compartida entre hilos (el TestClient corre en otro)."""
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = Session(engine)
    tenant = Tenant(external_id="dv-test", name="DV test")
    db.add(tenant)
    db.flush()
    db.info["tenant_id"] = tenant.id
    return db


def test_endpoint_contrato_y_rotulo():
    db = _db_mt()
    _seed(db, "EP", pb="0.7", yld="0.08", yield_status=STATUS_DISAGREE,
          y_trace={"desacuerdo_fuentes": True, "finnhub_yield_indicated": "0.20"})

    app = FastAPI()
    app.include_router(propicks_route.router, prefix="/api/propicks")
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)

    resp = client.get("/api/propicks/deep-value", params={"pb_max": "1.0"})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["estrategia"] == STRATEGY_ID
    assert "No es el filtro de calidad" in payload["rotulo"]
    (row,) = payload["resultados"]
    assert row["ticker"] == "EP"
    assert row["price_to_book"] == 0.7
    assert row["dividend_yield"] == 0.08
    assert row["desacuerdo_fuentes"] is True
    assert row["yield_status"] == STATUS_DISAGREE
    assert row["finnhub_yield_indicated"] == 0.2

    # Validacion de parametros
    assert client.get("/api/propicks/deep-value", params={"pb_max": "0"}).status_code == 422
    assert client.get("/api/propicks/deep-value", params={"yield_min": "2"}).status_code == 422


def test_endpoint_sin_metricas_da_lista_vacia_honesta():
    db = _db_mt()
    app = FastAPI()
    app.include_router(propicks_route.router, prefix="/api/propicks")
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)
    resp = client.get("/api/propicks/deep-value")
    assert resp.status_code == 200
    assert resp.json()["resultados"] == []


def test_yield_antiguo_con_pb_fresco_se_sirve_como_nd():
    """Caveat del auditor: la frescura se aplicaba solo al P/B y un yield de
    hace un mes se servia junto a un P/B de hoy sin aviso. Fail-closed: el
    yield viejo se trata como ausencia de dato (N/D), no como cifra."""
    db = _db()
    company = _company("VIEJO")
    db.add(company)
    db.flush()
    _metric(db, company, METRIC_PB, "0.8", TODAY.isoformat(), trace={
        "price_date": TODAY.isoformat(), "fiscal_year": 2025, "equity_source": "SEC",
    })
    stale = (TODAY - timedelta(days=30)).isoformat()
    _metric(db, company, METRIC_YIELD, "0.08", stale)
    rows = find_deep_value(db, pb_max=Decimal("1.0"), today=TODAY)
    assert [r.ticker for r in rows] == ["VIEJO"]  # el P/B fresco sigue sirviendose
    assert rows[0].dividend_yield is None
    assert rows[0].yield_status is None
    assert rows[0].desacuerdo_fuentes is False
    assert rows[0].finnhub_yield_indicated is None
    # y con yield_min>0 la empresa queda excluida: sin dato no cumple el umbral
    assert find_deep_value(db, pb_max=Decimal("1.0"), yield_min=Decimal("0.03"), today=TODAY) == []
