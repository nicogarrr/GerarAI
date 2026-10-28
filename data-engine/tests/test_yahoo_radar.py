"""Radar Yahoo (B1): parseo fail-closed, unidades por campo, cotejo y contrato
de no-persistencia. Sin red: fetcher inyectado con payload grabado."""
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes import propicks as propicks_route
from app.core.database import Base, get_db
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
# Claves verificadas contra el Yahoo real (28-oct): priceToBook (ratio),
# dividendYield (porcentaje), trailingAnnualDividendYield (fraccion).
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
                        "priceToBook": {"raw": 0.22, "fmt": "0.22"},
                        "dividendYield": {"raw": 8.1, "fmt": "8.10%"},
                        "trailingAnnualDividendYield": {"raw": 0.081},
                    },
                    {
                        "symbol": "VALU",
                        "shortName": "Valu Bancorp",
                        "fullExchangeName": "NYSE",
                        "currency": "USD",
                        "priceToBook": 0.45,
                        "trailingAnnualDividendYield": 0.082,
                    },
                    {
                        "symbol": "EXTR",
                        "fullExchangeName": "NYSE",
                        "currency": "USD",
                        "priceToBook": 0.9,
                        "dividendYield": {"raw": 27.0},
                    },
                    {
                        "symbol": "MINI",
                        "fullExchangeName": "BME",
                        "currency": "EUR",
                        "priceToBook": 0.6,
                    },
                    {
                        # 0 ambiguo de Yahoo (HK pese a pasar filtro): N/D, no 0,0%
                        "symbol": "CERO.HK",
                        "fullExchangeName": "HKSE",
                        "currency": "HKD",
                        "priceToBook": 0.3,
                        "dividendYield": 0,
                        "trailingAnnualDividendYield": 0,
                    },
                    {
                        "symbol": "NEG",
                        "fullExchangeName": "HKSE",
                        "currency": "HKD",
                        "priceToBook": -0.002,  # equity negativo: fail-closed
                    },
                    {"longName": "Sin simbolo SA"},
                ]
            }
        ]
    }
}


def test_query_pura_solo_operadores_y_campos_verificados():
    """Yahoo real (28-oct): `in` da 400; regiones van como or-de-eq. No existe
    filtro P/B (pricebookratio se ignora en silencio): la query NO lo lleva.
    dividendyield filtra en porcentaje (0.05 -> 5.0)."""
    q = radar.build_screener_query(yield_min=Decimal("0.05"), regions=["HK", "us"], size=500)
    ops = q["query"]["operands"]
    assert {"operator": "or", "operands": [
        {"operator": "eq", "operands": ["region", "hk"]},
        {"operator": "eq", "operands": ["region", "us"]},
    ]} in ops
    assert {"operator": "gt", "operands": ["dividendyield", 5.0]} in ops
    assert all("pricebook" not in str(op).lower() for op in ops)  # nunca pb en query
    assert q["size"] == radar.MAX_SIZE  # cap
    # una sola region: eq directo, sin or innecesario
    q2 = radar.build_screener_query(yield_min=Decimal("0"), regions=["es"], size=10)
    assert q2["query"]["operands"] == [{"operator": "eq", "operands": ["region", "es"]}]


def test_parseo_unidades_por_campo_y_fail_closed():
    out = radar.parse_screener_quotes(FIXTURE)
    by = {c.symbol: c for c in out}
    assert "SIN SIMBOLO" not in by and len(out) == 6  # el sin symbol se descarta
    hk = by["0883.HK"]
    assert hk.price_to_book == Decimal("0.22")
    # trailingAnnualDividendYield (fraccion) manda sobre dividendYield (%)
    assert hk.dividend_yield == Decimal("0.081")
    us = by["VALU"]
    assert us.dividend_yield == Decimal("0.082")  # fraccion, intacto
    extr = by["EXTR"]
    assert extr.dividend_yield == Decimal("0.27")  # solo % presente: /100
    assert extr.yield_extremo_revisar is True  # 27% > umbral extremo
    mini = by["MINI"]
    assert mini.price_to_book == Decimal("0.6") and mini.dividend_yield is None
    cero = by["CERO.HK"]
    assert cero.dividend_yield is None  # 0 ambiguo de Yahoo: N/D, nunca 0,0%
    assert by["NEG"].price_to_book is None  # pb negativo (equity<0): fail-closed
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
    # pb por defecto 1.0 en cliente: todos los del fixture pasan salvo NEG
    # (sin cifra de pb -> fail-closed, fuera del radar)
    assert "NEG" not in by
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
    assert hk["price_to_book"] == pytest.approx(0.22)


def test_pb_max_filtra_en_cliente_fail_closed():
    """pb_max=0.4: entran 0883.HK (0.22) y CERO.HK (0.3); fuera VALU (0.45),
    EXTR (0.9), MINI (0.6) y NEG (sin cifra). Sin pb_max no hay filtro."""
    db = _db()
    rows = radar.run_radar(db, fetcher=lambda q: FIXTURE, regions=["hk"], pb_max=Decimal("0.4"))[0]
    assert sorted(c.symbol for c in rows) == ["0883.HK", "CERO.HK"]
    rows_all = radar.run_radar(db, fetcher=lambda q: FIXTURE, regions=["hk"], pb_max=None)[0]
    assert "VALU" in {c.symbol for c in rows_all}
    assert "NEG" in {c.symbol for c in rows_all}  # sin filtro pb entra con N/D


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
