"""GET /api/portfolio/transactions (+ /page) con response_model: el wire es
el contrato.

La ruta devolvia schema free-form y el front tipaba a mano: review_flag
llegaba sin tipo. Estos tests ejercitan la respuesta HTTP real con
_transaction_payload real (sin mock del payload), incluida la rama de
compra a precio 0 (regalo/spin-off) y el filtro por ticker (sin depender
de la pagina 1 de un listado paginado).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import Company, Portfolio, Tenant, Transaction
from app.schemas.api import PortfolioTransactionOut
from tests.auth_helpers import auth_settings, signed_request

SECRET = "portfolio-transactions-route-test-secret-32c"


def _client(monkeypatch) -> tuple[TestClient, str, str]:
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET),
    )
    init_db()
    tenant_ext = f"portfolio-transactions-{uuid4().hex[:8]}"
    db = SessionLocal()
    db.add(Tenant(external_id=tenant_ext, name="Portfolio transactions route test"))
    db.commit()
    db.close()
    return TestClient(main.app), tenant_ext, "portfolio-transactions-user"


def _seed(tenant: str, ticker: str) -> None:
    db = SessionLocal()
    tenant_row = db.query(Tenant).filter(Tenant.external_id == tenant).one()
    db.info["tenant_id"] = tenant_row.id
    db.add(Portfolio(name="Main", base_currency="EUR", is_default=True))
    company = Company(
        ticker=ticker, name="Txn Co", exchange="BME", currency="EUR",
        sector="Tech", industry="I", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.commit()
    db.add_all([
        Transaction(
            company_id=company.id, trade_date=date(2026, 1, 15), action="buy",
            quantity=Decimal("100"), price=Decimal("10"), fees=Decimal("1.5"),
            currency="EUR", raw_payload={"notes": "primera compra"},
        ),
        # Compra a precio 0 (regalo/spin-off): aceptada pero marcada.
        Transaction(
            company_id=company.id, trade_date=date(2026, 3, 1), action="buy",
            quantity=Decimal("5"), price=Decimal("0"), fees=Decimal("0"),
            currency="EUR",
        ),
        Transaction(
            company_id=company.id, trade_date=date(2026, 5, 20), action="sell",
            quantity=Decimal("40"), price=Decimal("12"), fees=Decimal("1"),
            currency="EUR",
        ),
    ])
    db.commit()
    db.close()


def test_transactions_empty_portfolio(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)

    res = signed_request(client, SECRET, tenant, user, "GET", "/api/portfolio/transactions")

    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["items"] == []
    assert payload["page_info"]["total_items"] == 0


def test_transactions_full_wire_and_review_flag(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)
    _seed(tenant, f"TXN{tenant[-2:].upper()}")

    res = signed_request(
        client, SECRET, tenant, user, "GET", "/api/portfolio/transactions",
        params={"ticker": f"TXN{tenant[-2:].upper()}"},
    )

    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["page_info"]["total_items"] == 3
    items = payload["items"]
    for item in items:
        PortfolioTransactionOut.model_validate(item)
        assert item["ticker"] == f"TXN{tenant[-2:].upper()}"
    by_date = {item["trade_date"]: item for item in items}

    first = by_date["2026-01-15"]
    assert first["notes"] == "primera compra"
    assert first["review_flag"] is None  # clave sin tipo en el front
    assert first["fees"] == 1.5
    assert first["created_at"]
    assert first["updated_at"]

    gift = by_date["2026-03-01"]
    assert gift["review_flag"] is not None  # compra a precio 0 marcada
    assert gift["notes"] is None

    assert by_date["2026-05-20"]["action"] == "sell"


def test_transactions_page_limit_offset(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)
    _seed(tenant, f"TXN{tenant[-2:].upper()}")

    res = signed_request(
        client, SECRET, tenant, user, "GET", "/api/portfolio/transactions/page",
        params={"limit": 50, "offset": 0, "ticker": f"TXN{tenant[-2:].upper()}"},
    )

    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["total"] == 3
    assert len(payload["items"]) == 3
    for item in payload["items"]:
        PortfolioTransactionOut.model_validate(item)
