"""POST /api/portfolio/import/ibkr/csv con response_model.

Forma medida contra IBKRImportService.import_ibkr_csv: exito -> 8 claves
siempre; un CSV sin identificador de operacion emite identity_warning
(rama has_rows_without_id medida). Errores -> 400. Servicio real, sin mock.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import Tenant
from app.schemas.api import PortfolioIbkrCsvImportOut
from tests.auth_helpers import auth_settings, signed_request

SECRET = "portfolio-ibkr-csv-test-secret---"


def _client(monkeypatch) -> tuple[TestClient, str, str]:
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET),
    )
    init_db()
    tenant_ext = f"portfolio-ibkr-csv-{uuid4().hex[:8]}"
    db = SessionLocal()
    db.add(Tenant(external_id=tenant_ext, name="Portfolio ibkr csv test"))
    db.commit()
    db.close()
    return TestClient(main.app), tenant_ext, "portfolio-ibkr-csv-user"


def test_csv_import_wire(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)
    ticker = f"CSV{uuid4().hex[:4].upper()}"
    csv_text = f"symbol,action,quantity,price,date\n{ticker},buy,10,4.12,2025-01-10\n"

    res = signed_request(
        client, SECRET, tenant, user, "POST", "/api/portfolio/import/ibkr/csv",
        json_body={"csv": csv_text},
    )

    assert res.status_code == 200, res.text
    payload = res.json()
    PortfolioIbkrCsvImportOut.model_validate(payload)
    # Las 8 claves del exito, ni una mas ni una menos.
    assert set(payload) == {
        "status",
        "trades_imported",
        "duplicate_trades",
        "legacy_reimport_blocked",
        "identity_warning",
        "rows_skipped",
        "row_errors",
    }
    assert payload["status"] == "imported"
    assert payload["trades_imported"] == 1
    assert payload["duplicate_trades"] == 0
    # CSV sin identificador de operacion: aviso de identidad, medido.
    assert isinstance(payload["identity_warning"], str)
    assert payload["row_errors"] == []
