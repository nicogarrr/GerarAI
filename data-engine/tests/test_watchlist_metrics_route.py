"""GET /api/watchlist/metrics/{symbol} con response_model.

Forma medida contra la ruta: las cinco ramas de salida devuelven el mismo
envelope de 4 claves (market_cap, per, currency, sources); los huecos sin
base van a null, nunca se fabrica el numero. Servicio real, sin mock.
"""
from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import Company, Tenant
from tests.auth_helpers import auth_settings, signed_request

SECRET = "watchlist-metrics-secret-"


def _client(monkeypatch) -> tuple[TestClient, str, str]:
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET),
    )
    init_db()
    tenant_ext = f"watchlist-metrics-{uuid4().hex[:8]}"
    db = SessionLocal()
    db.add(Tenant(external_id=tenant_ext, name="Watchlist metrics test"))
    db.commit()
    db.close()
    return TestClient(main.app), tenant_ext, "watchlist-metrics-user"


def test_metrics_unknown_symbol(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)

    res = signed_request(client, SECRET, tenant, user, "GET", "/api/watchlist/metrics/NOPE")

    assert res.status_code == 200, res.text
    payload = res.json()
    assert set(payload) == {"market_cap", "per", "currency", "sources"}
    assert payload["market_cap"] is None
    assert payload["per"] is None
    assert payload["currency"] is None
    assert payload["sources"] == []


def test_metrics_company_without_data(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)
    db = SessionLocal()
    # Ticker propio del archivo: la BD de tests es compartida por sesion y otro
    # archivo de watchlist ya siembra ACME (choque UNIQUE en companies.ticker).
    db.add(Company(ticker="ACMX", name="Acme Metrics", exchange="NYSE", currency="USD",
                   company_type="operating", valuation_model="unassigned"))
    db.commit()
    db.close()

    res = signed_request(client, SECRET, tenant, user, "GET", "/api/watchlist/metrics/ACMX")

    assert res.status_code == 200, res.text
    payload = res.json()
    assert set(payload) == {"market_cap", "per", "currency", "sources"}
    # Sin hechos financieros ni precios: huecos a null, divisa de la ficha.
    assert payload["market_cap"] is None
    assert payload["per"] is None
    assert payload["currency"] == "USD"
    assert payload["sources"] == []


def _seed_eps(ticker: str, rows: list[tuple[str, int, float]], tenant_ext: str) -> None:
    from datetime import date, timedelta
    from decimal import Decimal

    from sqlalchemy import select

    from app.models import FinancialFact, MarketPrice

    db = SessionLocal()
    tenant_id = db.scalar(select(Tenant.id).where(Tenant.external_id == tenant_ext))
    company = Company(ticker=ticker, name=ticker, exchange="NASDAQ", currency="USD",
                      company_type="operating", valuation_model="unassigned")
    db.add(company)
    db.commit()
    db.add(MarketPrice(company_id=company.id, date=date.today() - timedelta(days=1), open=11.88, high=11.88,
                       low=11.88, close=Decimal("11.88"), volume=1000, quote_currency="USD", source="test"))
    for period, fy, value in rows:
        db.add(FinancialFact(company_id=company.id, metric="eps_diluted", value=Decimal(str(value)),
                             unit="USD/share", period=period, fiscal_year=fy, fiscal_quarter="FY",
                             source_type="SEC", is_reported=True, tenant_id=tenant_id))
    db.commit()
    db.close()


def test_per_del_ultimo_ejercicio_aunque_sea_de_perdidas(monkeypatch) -> None:
    # AbCellera (BD local): BPA 0,50 en 2022 y pérdidas en 2023-2025. Antes: PER 23,8 con el BPA de 2022.
    from datetime import date

    client, tenant, user = _client(monkeypatch)
    y = date.today().year - 1
    _seed_eps("ABCX", tenant_ext=tenant, rows=[(f"{y - 3}-12-31:FY", y - 3, 0.50), (f"{y - 2}-12-31:FY", y - 2, -0.51),
                       (f"{y - 1}-12-31:FY", y - 1, -0.55), (f"{y}-12-31:FY", y, -0.49)])

    payload = signed_request(client, SECRET, tenant, user, "GET", "/api/watchlist/metrics/ABCX").json()

    assert payload["per"] is None
    assert any(s.startswith(f"PER: N/D: eps_diluted FY{y} = -0.49") for s in payload["sources"]), payload


def test_per_con_el_ultimo_ejercicio_con_beneficio(monkeypatch) -> None:
    from datetime import date

    client, tenant, user = _client(monkeypatch)
    y = date.today().year - 1
    _seed_eps("PERX", tenant_ext=tenant, rows=[(f"{y - 1}-12-31:FY", y - 1, -1.0), (f"{y}-12-31:FY", y, 0.50)])

    payload = signed_request(client, SECRET, tenant, user, "GET", "/api/watchlist/metrics/PERX").json()

    assert abs(payload["per"] - 23.76) < 1e-9
