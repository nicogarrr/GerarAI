"""Radar Yahoo (B1): parseo fail-closed, unidades por campo, cotejo y contrato
de no-persistencia. Sin red: fetcher inyectado con payload grabado."""
from datetime import date
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes import propicks as propicks_route
from app.core.database import Base, get_db
from app.core.database import Base
from app.models import CalculatedMetric, FinancialFact, Tenant
from app.services import yahoo_radar_service as radar
from tests.test_propicks_prices import _company, _db


def _db_mt() -> Session:
    # SQLite en memoria compartida entre hilos (el TestClient corre en otro).
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = Session(engine)
    tenant = Tenant(external_id="radar-test", name="Radar test")
    db.add(tenant)
    db.flush()
    db.info["tenant_id"] = tenant.id
    return db

# Payload grabado con la forma real del screener Yahoo (formatted=false):
# dividendYield en porcentaje, trailingAnnualDividendYield en fraccion,
# numericos como {raw, fmt}.
FIXTURE = {
    "finance": {
        "result": [
            {
                "quotes": [
                    {
                        "symbol": "0883.HK",
                        "longName": "HK Properties Ltd",
                        "fullExchangeName": "HKEX",
                        "currency": "HKD",
                        "priceToBookRatio": {"raw": 0.22, "fmt": "0.22"},
                        "dividendYield": {"raw": 8.1, "fmt": "8.10%"},
                    },
                    {
                        "symbol": "VALU",
                        "shortName": "Valu Bancorp",
                        "fullExchangeName": "NYSE",
                        "currency": "USD",
                        "priceToBookRatio": 0.45,
                        "trailingAnnualDividendYield": 0.082,
                    },
                    {
                        "symbol": "EXTR",
                        "fullExchangeName": "NYSE",
                        "currency": "USD",
                        "dividendYield": {"raw": 27.0},
                    },
                    {
                        "symbol": "MINI",
                        "fullExchangeName": "BME",
                        "currency": "EUR",
                    },
                    {"longName": "Sin simbolo SA"},
                ]
            }
        ]
    }
}


def test_query_pura_operadores_y_regiones():
    q = radar.build_screener_query(
        pb_max=Decimal("1.0"), yield_min=Decimal("0.05"),
        regions=["HK", "us"], size=500,
    )
    ops = q["query"]["operands"]
    assert {"operator": "in", "operands": ["region", ["hk", "us"]]} in ops
    assert {"operator": "lt", "operands": ["pricebookratio", 1.0]} in ops
    assert {"operator": "gt", "operands": ["dividendyield", 0.05]} in ops
    assert q["size"] == radar.MAX_SIZE  # cap
    # sin filtro pb ni yield: solo region
    q2 = radar.build_screener_query(pb_max=None, yield_min=Decimal("0"), regions=["es"], size=10)
    assert q2["query"]["operands"] == [{"operator": "in", "operands": ["region", ["es"]]}]


def test_parseo_unidades_por_campo_y_fail_closed():
    out = radar.parse_screener_quotes(FIXTURE)
    by = {c.symbol: c for c in out}
    assert "SIN SIMBOLO" not in by and len(out) == 4  # el sin symbol se descarta
    hk = by["0883.HK"]
    assert hk.price_to_book == Decimal("0.22")
    assert hk.dividend_yield == Decimal("8.1") / Decimal(100)  # % -> fraccion
    us = by["VALU"]
    assert us.dividend_yield == Decimal("0.082")  # ya fraccion, intacto
    assert by["EXTR"].yield_extremo_revisar is True  # 27% > umbral extremo
    mini = by["MINI"]
    assert mini.price_to_book is None and mini.dividend_yield is None  # N/D, no 0
    assert all(c.fuente == radar.YAHOO_LABEL for c in out)


def test_parseo_payload_malformado_no_explota():
    assert radar.parse_screener_quotes({}) == []
    assert radar.parse_screener_quotes({"finance": {"result": []}}) == []
    assert radar.parse_screener_quotes({"finance": {"result": [{"quotes": "no-lista"}]}}) == []


def test_radar_marca_universo_propio_y_via_cotejo_sin_escribir_nada():
    db = _db()
    db.add(_company("VALU"))
    db.flush()
    facts_antes = db.query(FinancialFact).count()
    metrics_antes = db.query(CalculatedMetric).count()
    candidates, generado_en, regions = radar.run_radar(
        db, fetcher=lambda q: FIXTURE, regions=["hk", "us"]
    )
    by = {c.symbol: c for c in candidates}
    assert by["VALU"].en_universo_propio is True
    assert by["0883.HK"].en_universo_propio is False
    assert by["0883.HK"].via_cotejo == radar.HKEXNEWS_SEARCH_URL
    assert by["VALU"].via_cotejo is None
    assert regions == ["hk", "us"]
    assert generado_en.endswith("+00:00")
    # contrato: el radar no persiste propuestas como hechos
    assert db.query(FinancialFact).count() == facts_antes
    assert db.query(CalculatedMetric).count() == metrics_antes


def test_endpoint_ok_y_rotulo_no_oficial(monkeypatch):
    monkeypatch.setattr(radar, "fetch_screener", lambda q: FIXTURE)
    db = _db_mt()
    app = FastAPI()
    app.include_router(propicks_route.router, prefix="/api/propicks")
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)
    r = client.get("/api/propicks/deep-value/radar", params={"regions": "hk,us"})
    assert r.status_code == 200
    body = r.json()
    assert "fuente no oficial" in body["rotulo"]
    assert "HKEXnews" in body["rotulo"]
    assert body["regiones"] == ["hk", "us"]
    hk = next(c for c in body["candidatos"] if c["symbol"] == "0883.HK")
    assert hk["fuente"] == radar.YAHOO_LABEL
    assert hk["via_cotejo"] == radar.HKEXNEWS_SEARCH_URL
    assert hk["dividend_yield"] == pytest.approx(0.081)


def test_endpoint_503_honesto_si_yahoo_falla(monkeypatch):
    def boom(q):
        raise RuntimeError("yahoo caido")

    monkeypatch.setattr(radar, "fetch_screener", boom)
    db = _db_mt()
    app = FastAPI()
    app.include_router(propicks_route.router, prefix="/api/propicks")
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)
    r = client.get("/api/propicks/deep-value/radar")
    assert r.status_code == 503
    assert "no disponible" in r.json()["detail"]
