"""POST /api/portfolio/import/ibkr/xml con response_model.

Forma medida contra IBKRImportService.import_flex_xml (rama confirmada):
las 23 claves siempre. dry_run/reconcile destructivo nunca llegan al wire
desde la ruta (solo pasa expected_account_id y max_statement_age_days).
La ruta exige tenant propietario Flex (settings medidos en
_require_ibkr_owner). Servicio real, sin mock.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

import main
from app.api.routes import portfolio as portfolio_module
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import Tenant
from app.schemas.api import PortfolioIbkrXmlImportOut
from tests.auth_helpers import auth_settings, signed_request

SECRET = "portfolio-ibkr-xml-test-secret---"


def _client(monkeypatch) -> tuple[TestClient, str, str, int]:
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET),
    )
    init_db()
    tenant_ext = f"portfolio-ibkr-xml-{uuid4().hex[:8]}"
    db = SessionLocal()
    db.add(Tenant(external_id=tenant_ext, name="Portfolio ibkr xml test"))
    db.commit()
    tenant_id = db.query(Tenant).filter(Tenant.external_id == tenant_ext).one().id
    db.close()
    monkeypatch.setattr(
        portfolio_module,
        "get_settings",
        lambda: SimpleNamespace(
            ibkr_flex_tenant_id=tenant_id, ibkr_flex_account_id="U1"
        ),
    )
    return TestClient(main.app), tenant_ext, "portfolio-ibkr-xml-user", tenant_id


def test_xml_import_wire(monkeypatch) -> None:
    client, tenant, user, _ = _client(monkeypatch)
    day = date.today().strftime("%Y%m%d")
    xml = (
        '<FlexQueryResponse><FlexStatements><FlexStatement accountId="U1" '
        f'toDate="{day}"><Trade symbol="AAPL" tradeID="X1" buySell="BUY" '
        f'quantity="1" tradePrice="10" tradeDate="{day}"/>'
        "</FlexStatement></FlexStatements></FlexQueryResponse>"
    )

    res = signed_request(
        client, SECRET, tenant, user, "POST", "/api/portfolio/import/ibkr/xml",
        json_body={"xml": xml},
    )

    assert res.status_code == 200, res.text
    payload = res.json()
    PortfolioIbkrXmlImportOut.model_validate(payload)
    # Las 23 claves de la rama confirmada, ni una mas ni una menos.
    assert set(payload) == {
        "status",
        "price_backfills_enqueued",
        "positions_imported",
        "valuation_hold_kept",
        "cost_review_required",
        "cash_imported",
        "trades_imported",
        "raw_rows_stored",
        "raw_rows_already_present",
        "raw_rows_pruned",
        "fx_conversions_imported",
        "fx_conversions_skipped",
        "trades_cancelled",
        "dividends_imported",
        "fees_imported",
        "cash_transactions_imported",
        "rows_skipped",
        "unattributed_cash_rows",
        "row_errors",
        "positions_closed",
        "cash_removed",
        "reconcile_blocked",
        "portfolio_snapshot_id",
    }
    assert payload["status"] == "imported"
    assert payload["trades_imported"] == 1
    assert payload["row_errors"] == []
    assert payload["portfolio_snapshot_id"] > 0
