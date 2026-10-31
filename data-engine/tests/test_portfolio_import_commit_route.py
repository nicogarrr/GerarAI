"""POST /api/portfolio/import/commit con response_model.

Forma medida contra TransactionImportService.commit_import: exito -> 5
claves siempre (success/message/imported_count/duplicates_skipped/
import_batch); errores -> 400. Reimportar el mismo lote omite duplicados
(lote estable por contenido). Servicio real, sin mock.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import Company, Tenant
from app.schemas.api import PortfolioImportCommitOut
from tests.auth_helpers import auth_settings, signed_request

SECRET = "portfolio-import-commit-secret--"


def _client(monkeypatch) -> tuple[TestClient, str, str]:
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET),
    )
    init_db()
    tenant_ext = f"portfolio-import-commit-{uuid4().hex[:8]}"
    db = SessionLocal()
    db.add(Tenant(external_id=tenant_ext, name="Portfolio import commit test"))
    db.commit()
    db.close()
    return TestClient(main.app), tenant_ext, "portfolio-import-commit-user"


def _seed_company(tenant_ext: str) -> str:
    db = SessionLocal()
    tenant_row = db.query(Tenant).filter(Tenant.external_id == tenant_ext).one()
    db.info["tenant_id"] = tenant_row.id
    ticker = f"IMP{uuid4().hex[:4].upper()}"
    db.add(Company(
        ticker=ticker, name="Import commit test co", exchange="TEST",
        currency="EUR", company_type="stock", valuation_model="dcf",
    ))
    db.commit()
    db.close()
    return ticker


def test_commit_wire_and_reimport_dedup(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)
    ticker = _seed_company(tenant)
    body = {
        "transactions": [
            {
                "row_number": 2,
                "ticker": ticker,
                "date": "2026-10-29",
                "action": "buy",
                "quantity": 3,
                "price": 50,
                "fees": 1,
                "currency": "EUR",
            }
        ],
        "source_filename": "extracto.csv",
    }

    res = signed_request(
        client, SECRET, tenant, user, "POST", "/api/portfolio/import/commit",
        json_body=body,
    )

    assert res.status_code == 200, res.text
    payload = res.json()
    PortfolioImportCommitOut.model_validate(payload)
    # Las 5 claves del exito, ni una mas ni una menos.
    assert set(payload) == {
        "success",
        "message",
        "imported_count",
        "duplicates_skipped",
        "import_batch",
    }
    assert payload["success"] is True
    assert payload["imported_count"] == 1
    assert payload["duplicates_skipped"] == 0
    assert payload["import_batch"].startswith("csv-")

    # Reimportar el mismo lote: mismo batch, pata omitida como duplicada.
    res2 = signed_request(
        client, SECRET, tenant, user, "POST", "/api/portfolio/import/commit",
        json_body=body,
    )
    assert res2.status_code == 200, res2.text
    payload2 = res2.json()
    PortfolioImportCommitOut.model_validate(payload2)
    assert payload2["import_batch"] == payload["import_batch"]
    assert payload2["imported_count"] == 0
    assert payload2["duplicates_skipped"] == 1
