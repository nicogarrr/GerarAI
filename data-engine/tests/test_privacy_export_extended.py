"""Portable private records remain tenant-scoped and never include credentials."""
import json
from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import FxConversion, IbkrRawRow, Tenant, TenantLLMSettings, WorkflowRun
from app.services.privacy_service import EXPORT_TABLES, PrivacyService


def test_new_categories_are_registered():
    keys = {key for key, _ in EXPORT_TABLES}
    assert {"ibkr_raw_rows", "fx_conversions", "dca_signal_states", "dca_evaluation_runs",
            "tenant_llm_settings", "budget_usage", "workflow_runs", "workflow_step_runs"} <= keys


def test_extended_export_isolates_two_tenants_and_redacts_nested_secrets(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(PrivacyService, "_audit", lambda *a, **kw: None)
    with Session(engine) as db:
        tenants = [Tenant(external_id=f"export-{i}", name=f"Tenant{i}") for i in range(2)]
        db.add_all(tenants)
        db.flush()
        for i, tenant in enumerate(tenants):
            db.info["tenant_id"] = tenant.id
            db.add(IbkrRawRow(section="Trade", path="Trade", row_hash=str(i)*64,
                              payload={"symbol": f"PRIVATE{i}", "secret": "do-not-export"}))
            db.add(FxConversion(trade_date=date(2026, 10, 28), disposed_currency="EUR",
                                disposed_amount=Decimal("10"), acquired_currency="USD", acquired_amount=Decimal("11")))
            db.add(TenantLLMSettings(provider="test", api_key_ciphertext="cipher-do-not-export", api_key_last4="abcd"))
            db.add(WorkflowRun(workflow_name=f"PRIVATE{i}", input_payload={"nested": {"api_key": "nested-secret", "text": "portable"}}))
            db.flush()
        db.info["tenant_id"] = tenants[0].id
        data = PrivacyService().export_account(db)
        assert data["schema_version"] == 2
        assert len(data["ibkr_raw_rows"]) == len(data["fx_conversions"]) == len(data["tenant_llm_settings"]) == 1
        assert data["ibkr_raw_rows"][0]["payload"]["symbol"] == "PRIVATE0"
        dumped = json.dumps(data)
        for forbidden in ("PRIVATE1", "do-not-export", "cipher-do-not-export", "nested-secret", "api_key_ciphertext", "api_key_last4"):
            assert forbidden not in dumped
        assert data["workflow_runs"][0]["input_payload"]["nested"]["text"] == "portable"
