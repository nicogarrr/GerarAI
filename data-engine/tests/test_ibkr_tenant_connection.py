from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.core.database import SessionLocal, init_db
from app.core.llm_settings_crypto import decrypt_api_key
from app.models import IBKRConnection, Tenant
from app.services import ibkr_connection_service as service
from app.services.connectors.ibkr import IBKRFlexClient


def settings():
    return Settings(_env_file=None, app_env="test", llm_settings_encryption_key="test-ibkr-key-at-least-thirty-two-bytes")


def report(account="U123456", position_date=None, cash_date=None):
    today = date.today().strftime("%Y%m%d")
    return f'''<FlexQueryResponse><FlexStatements><FlexStatement accountId="{account}" toDate="{today}">
    <OpenPositions><OpenPosition accountId="{account}" symbol="TEST" assetCategory="STK" currency="USD" position="2" markPrice="10" costBasisPrice="9" reportDate="{position_date or today}" /></OpenPositions>
    <CashReport><CashReportCurrency accountId="{account}" currency="USD" endingCash="5" endingSettledCash="5" reportDate="{cash_date or today}" /></CashReport>
    </FlexStatement></FlexStatements></FlexQueryResponse>'''


def tenant(db):
    row = Tenant(external_id=uuid4().hex, name="synthetic")
    db.add(row)
    db.flush()
    db.info["tenant_id"] = row.id
    return row.id


def save(db, account="U123456"):
    return service.save_connection(db, settings(), token="1234567890123456", query_id="12345", account_id=account, complete_query=False, statement_date=date.today())


def test_report_gate_requires_same_account_dates_and_both_sections():
    assert service.check_report(report(), "U123456") == date.today()
    for xml in [report(account="U999999"), report(position_date="20200101"), report(cash_date="20200101"), report().replace("CashReport", "WrongSection")]:
        with pytest.raises(service.ConnectionError):
            service.check_report(xml, "U123456")


def test_connection_ciphertext_and_view_never_exposes_token():
    init_db()
    with SessionLocal() as db:
        tenant(db)
        result = save(db)
        row = service.connection(db)
        assert row is not None
        assert "1234567890123456" not in str(result)
        assert row.token_ciphertext != "1234567890123456"
        assert decrypt_api_key(row.token_ciphertext, settings()) == "1234567890123456"
        assert "token" not in str(result)


def test_two_tenants_cannot_read_change_disconnect_others():
    init_db()
    with SessionLocal() as db:
        a = tenant(db)
        save(db)
        b = tenant(db)
        assert a != b
        assert not service.view(db)["connected"]
        save(db, "U222222")
        service.disconnect(db)
        db.info["tenant_id"] = a
        assert service.view(db)["connected"]
        assert service.view(db)["account_id"] == "U123456"
        with pytest.raises(service.ConnectionError):
            save(db, "U999999")


def test_disconnect_erases_ciphertext_and_prevents_download_credentials():
    init_db()
    with SessionLocal() as db:
        tenant(db)
        save(db)
        token, query, account, rev = service.credentials(db, settings())
        service.disconnect(db)
        assert service.connection(db).token_ciphertext is None
        with pytest.raises(service.ConnectionError):
            service.credentials(db, settings())
        with pytest.raises(service.ConnectionError):
            service.import_report(db, report(), account, rev)


def test_missing_tenant_fails_closed():
    init_db()
    with SessionLocal() as db:
        with pytest.raises(service.ConnectionError):
            service.view(db)


def test_explicit_empty_credentials_never_inherit_server_defaults(monkeypatch):
    import app.services.connectors.ibkr as client_module
    monkeypatch.setattr(client_module, "get_settings", lambda: Settings(_env_file=None, ibkr_flex_token="server-token", ibkr_flex_query_id="server-query"))
    assert IBKRFlexClient().configured()
    assert not IBKRFlexClient(token="", query_id="").configured()


def test_only_one_connection_per_tenant_and_no_cross_tenant_raw_query():
    init_db()
    with SessionLocal() as db:
        a = tenant(db)
        save(db)
        save(db)
        assert len(db.scalars(select(IBKRConnection)).all()) == 1
        tenant(db)
        assert db.scalars(select(IBKRConnection)).all() == []
        assert a != db.info["tenant_id"]


def test_no_import_until_verified_and_revision_is_current(monkeypatch):
    init_db()
    calls = []
    monkeypatch.setattr(service.IBKRImportService, "import_flex_xml", lambda self, db, xml, **kw: calls.append(kw) or {})
    with SessionLocal() as db:
        tenant(db)
        save(db)
        _, _, account, revision = service.credentials(db, settings())
        with pytest.raises(service.ConnectionError):
            service.import_report(db, report(account="U999999"), account, revision)
        assert calls == []
        result = service.import_report(db, report(), account, revision)
        assert result["status"] == "partial"
        assert calls[0]["expected_account_id"] == account
        assert calls[0]["reconcile"] is False
        assert result["last_success_at"] is not None


def test_changed_token_during_download_cannot_import_old_report(monkeypatch):
    init_db()
    calls = []
    monkeypatch.setattr(service.IBKRImportService, "import_flex_xml", lambda *a, **kw: calls.append(kw))
    with SessionLocal() as db:
        tenant(db)
        save(db)
        _, _, account, revision = service.credentials(db, settings())
        save(db)
        with pytest.raises(service.ConnectionError):
            service.import_report(db, report(), account, revision)
        assert calls == []


def test_connection_routes_verify_before_save_and_return_safe_failure(monkeypatch):
    import asyncio

    from fastapi import HTTPException

    from app.api.routes import settings as routes
    init_db()
    monkeypatch.setattr(routes, "get_settings", settings)
    async def wrong(*args):
        return report(account="U999999")
    monkeypatch.setattr(service, "download", wrong)
    with SessionLocal() as db:
        tenant(db)
        with pytest.raises(HTTPException) as caught:
            asyncio.run(routes.connect_ibkr(routes.IBKRConnectRequest(token="1234567890123456", query_id="12345", account_id="U123456"), db))
        assert caught.value.status_code == 422
        assert "1234567890123456" not in caught.value.detail
        assert service.connection(db) is None


def test_legacy_import_guard_does_not_revive_disconnected_connection(monkeypatch):
    from fastapi import HTTPException

    from app.api.routes.portfolio import _require_ibkr_owner
    init_db()
    with SessionLocal() as db:
        tenant(db)
        save(db)
        service.disconnect(db)
        from app.api.routes import portfolio
        monkeypatch.setattr(portfolio, "get_settings", lambda: settings().model_copy(update={"ibkr_flex_tenant_id": db.info["tenant_id"], "ibkr_flex_account_id": "U123456"}))
        with pytest.raises(HTTPException) as caught:
            _require_ibkr_owner(db)
        assert caught.value.status_code == 409


def test_partial_sync_is_not_reported_as_complete(monkeypatch):
    init_db()
    monkeypatch.setattr(service.IBKRImportService, "import_flex_xml", lambda *a, **kw: {"rows_skipped": 1})
    with SessionLocal() as db:
        tenant(db)
        save(db)
        _, _, account, revision = service.credentials(db, settings())
        assert service.import_report(db, report(), account, revision)["status"] == "partial"


def test_repeated_real_import_is_idempotent_and_tenant_isolated(monkeypatch):
    import app.services.market_close_sync as price_sync
    from app.models import CashBalance, Position
    monkeypatch.setattr(price_sync, "enqueue_price_backfills", lambda *args, **kw: 0)
    init_db()
    with SessionLocal() as db:
        a = tenant(db)
        save(db)
        _, _, account, revision = service.credentials(db, settings())
        service.import_report(db, report(), account, revision)
        service.import_report(db, report(), account, revision)
        assert len(db.scalars(select(Position)).all()) == 1
        assert len(db.scalars(select(CashBalance)).all()) == 1
        tenant(db)
        assert db.scalars(select(Position)).all() == []
        assert db.scalars(select(CashBalance)).all() == []
        db.info["tenant_id"] = a
        assert len(db.scalars(select(Position)).all()) == 1
