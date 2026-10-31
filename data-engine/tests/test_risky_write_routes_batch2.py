"""Rutas de escritura de riesgo sin test directo (lote 2): import por imagen.

POST /api/portfolio/image/confirm escribe posiciones reales en la cartera
(dinero). El servicio confirm_review ya tiene cobertura; aqui se prueba el
cable HTTP: firma obligatoria, validacion 422 y aislamiento de tenant a
traves de la capa de rutas.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import Company, Tenant
from app.services import portfolio_image_import as imports
from app.services.portfolio_image_import import ConfirmedImageRow, review_rows
from tests.auth_helpers import auth_settings, signed_request

SECRET = "risky-write-routes-b2-test-secret-at-least-32-chars"


def _setup(monkeypatch):
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET),
    )
    init_db()
    suffix = uuid4().hex[:8]
    ext_a, ext_b = f"img-a-{suffix}", f"img-b-{suffix}"
    db = SessionLocal()
    db.add_all(
        [
            Tenant(external_id=ext_a, name="Img A"),
            Tenant(external_id=ext_b, name="Img B"),
        ]
    )
    if not db.query(Company).filter_by(ticker="ASTS").first():
        db.add(
            Company(
                ticker="ASTS",
                name="AST SpaceMobile",
                currency="USD",
                exchange="NASDAQ",
                sector="Tech",
                industry="Space",
                company_type="standard",
                valuation_model="standard_dcf",
            )
        )
    db.commit()
    tenant_a = db.query(Tenant).filter_by(external_id=ext_a).one().id
    db.close()

    from app.services.extended_quote_service import ExtendedQuote

    now = int(datetime.now(UTC).timestamp())
    quote = ExtendedQuote(
        ticker="ASTS", status="available", price=42, currency="USD",
        timestamp=now, fetched_at=now,
    )
    monkeypatch.setattr(imports.extended_quote_service, "get", AsyncMock(return_value=quote))
    return TestClient(main.app), ext_a, ext_b, tenant_a


def _review_for(tenant_db_id: int) -> int:
    db = SessionLocal()
    db.info["tenant_id"] = tenant_db_id
    try:
        result = asyncio.run(
            review_rows(db, uuid4().hex * 2, [ConfirmedImageRow(ticker="ASTS", quantity="1", currency="USD", confirmed=True)])
        )
        return result["review_id"]
    finally:
        db.close()


def test_confirm_route_requires_confirmation_flag(monkeypatch):
    client, ext_a, _, tenant_a = _setup(monkeypatch)
    review_id = _review_for(tenant_a)
    res = signed_request(
        client, SECRET, ext_a, "u1", "POST", "/api/portfolio/image/confirm",
        json_body={"review_id": review_id, "confirmed": False},
    )
    assert res.status_code == 422, res.text


def test_confirm_route_isolates_other_tenants_review(monkeypatch):
    """Un review_id del tenant A no es confirmable por el tenant B (dinero)."""
    client, ext_a, ext_b, tenant_a = _setup(monkeypatch)
    review_id = _review_for(tenant_a)
    res = signed_request(
        client, SECRET, ext_b, "u2", "POST", "/api/portfolio/image/confirm",
        json_body={"review_id": review_id, "confirmed": True},
    )
    assert res.status_code == 422, res.text
    assert "no existe" in res.text
