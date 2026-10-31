"""GET /api/portfolio/dividends y /dividends/projection con response_model.

Las dos rutas devolvian schema free-form sin tipo en el front ni verificacion
de contrato (contract-drift no chequea rutas sin response_model). Servicio
real contra SQLite, sin mock del payload. La rama fiscal "sin datos" de la
proyeccion OMITE effective_avg_rate y per_position: la ruta usa
response_model_exclude_unset=True y aqui se comprueba la ausencia.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import Company, DividendRecord, Position, Tenant
from app.schemas.api import PortfolioDividendProjectionOut, PortfolioDividendYieldsOut
from tests.auth_helpers import auth_settings, signed_request

SECRET = "portfolio-dividends-route-test-sec"


def _client(monkeypatch) -> tuple[TestClient, str, str]:
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET),
    )
    init_db()
    tenant_ext = f"portfolio-dividends-{uuid4().hex[:8]}"
    db = SessionLocal()
    db.add(Tenant(external_id=tenant_ext, name="Portfolio dividends route test"))
    db.commit()
    db.close()
    return TestClient(main.app), tenant_ext, "portfolio-dividends-user"


def _seed(db, tenant_ext: str, *, currency: str, ticker_suffix: str) -> Company:
    suffix = uuid4().hex[:4].upper()
    company = Company(
        ticker=f"DVD{ticker_suffix}{suffix}",
        name="Dividend route test co",
        exchange="TEST",
        currency=currency,
        company_type="stock",
        valuation_model="dcf",
    )
    db.add(company)
    db.flush()
    db.add(Position(
        company_id=company.id,
        quantity=Decimal("10"),
        average_cost=Decimal("90"),
        market_price=Decimal("100"),
        market_value=Decimal("1000"),
        currency=currency,
        market_value_base=Decimal("1000"),
    ))
    return company


def test_dividends_empty(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)

    res = signed_request(client, SECRET, tenant, user, "GET", "/api/portfolio/dividends")

    assert res.status_code == 200, res.text
    payload = res.json()
    PortfolioDividendYieldsOut.model_validate(payload)
    # Sin posiciones propias del tenant: el agregado es None (desconocido),
    # nunca 0.0 fabricado.
    assert payload["portfolio_yield"] is None
    assert payload["coverage"]["positions"] == 0
    assert payload["coverage"]["positions_with_dividend_data"] == 0


def test_dividends_wire(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)
    db = SessionLocal()
    tenant_row = db.query(Tenant).filter(Tenant.external_id == tenant).one()
    db.info["tenant_id"] = tenant_row.id
    company = _seed(db, tenant, currency="EUR", ticker_suffix="W")
    db.add(DividendRecord(
        company_id=company.id,
        ex_date=date.today() - timedelta(days=180),
        amount=Decimal("2.0"),
        currency="EUR",
    ))
    db.commit()
    db.close()

    res = signed_request(client, SECRET, tenant, user, "GET", "/api/portfolio/dividends")

    assert res.status_code == 200, res.text
    payload = res.json()
    PortfolioDividendYieldsOut.model_validate(payload)
    mine = [p for p in payload["positions"] if p["ticker"] == company.ticker]
    assert len(mine) == 1
    pos = mine[0]
    assert pos["ttm_dividend_per_share"] == 2.0
    assert pos["dividend_yield"] == 0.02
    assert pos["records_12m"] == 1
    assert pos["skipped_currency_mismatch"] == 0
    assert pos["price"] == 100.0
    assert payload["portfolio_yield"] == 0.02
    assert payload["coverage"]["positions_with_dividend_data"] >= 1
    assert payload["provenance"]["coverage"] == "ok"


def test_projection_empty(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)

    res = signed_request(
        client, SECRET, tenant, user, "GET",
        "/api/portfolio/dividends/projection", params={"months": 3},
    )

    assert res.status_code == 200, res.text
    payload = res.json()
    PortfolioDividendProjectionOut.model_validate(payload)
    assert payload["horizon_months"] == 3
    assert 3 <= len(payload["months"]) <= 4  # frontera de mes: bucket extra
    assert payload["fiscal_by_year"] == {}
    assert payload["declared_future"] == []
    for bucket in payload["months"]:
        assert bucket["gross_base"] == 0.0
        assert bucket["note"] is None


def test_projection_fiscal_year_omits_scenario_keys(monkeypatch) -> None:
    # Posicion en USD sin tipo de cambio disponible: excluida por falta de FX.
    # La rama fiscal resultante ("sin datos") omite effective_avg_rate y
    # per_position; response_model_exclude_unset debe conservar la omision.
    client, tenant, user = _client(monkeypatch)
    db = SessionLocal()
    tenant_row = db.query(Tenant).filter(Tenant.external_id == tenant).one()
    db.info["tenant_id"] = tenant_row.id
    company = _seed(db, tenant, currency="USD", ticker_suffix="X")
    db.add(DividendRecord(
        company_id=company.id,
        ex_date=date.today() - timedelta(days=90),
        amount=Decimal("1.5"),
        currency="USD",
    ))
    db.commit()
    db.close()

    res = signed_request(client, SECRET, tenant, user, "GET", "/api/portfolio/dividends/projection")

    assert res.status_code == 200, res.text
    payload = res.json()
    PortfolioDividendProjectionOut.model_validate(payload)
    assert company.ticker in payload["gross_summary"]["excluded_no_fx"]
    assert payload["gross_summary"]["complete"] is False
    assert payload["fiscal_by_year"], "se esperaba al menos un año fiscal"
    for year_data in payload["fiscal_by_year"].values():
        assert "effective_avg_rate" not in year_data
        assert "per_position" not in year_data
        assert year_data["irpf_scenario"] is None
        assert year_data["gross_base"] is None
        assert company.ticker in year_data["excluded_tickers"]
    excluded_months = [m for m in payload["months"] if company.ticker in m["excluded_tickers"]]
    assert excluded_months, "la posicion excluida debe declararse en el bucket mensual"
    assert all(m["note"] for m in excluded_months)
