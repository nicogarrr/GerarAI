"""IBKR Flex: efectivo por divisa (CashReportCurrency) y cliente sin fugas de token."""
import asyncio
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.database import Base
from app.models import CashBalance, Position
from app.services.connectors.ibkr import IBKRFlexClient, IBKRFlexError
from app.services.ibkr_import_service import IBKRImportService
from tests.test_ibkr_import import _tenant_session

CASH = (
    '<CashReport>'
    '<CashReportCurrency currency="BASE_SUMMARY" levelOfDetail="BaseCurrency" fromDate="20261008" toDate="20261008" endingCash="-7969.27" endingSettledCash="-7144.80"/>'
    '<CashReportCurrency currency="AED" levelOfDetail="Currency" fromDate="20261008" toDate="20261008" endingCash="0.000013535" endingSettledCash="0.000013535"/>'
    '<CashReportCurrency currency="EUR" levelOfDetail="Currency" fromDate="20261008" toDate="20261008" endingCash="7433.60" endingSettledCash="7433.60"/>'
    '<CashReportCurrency currency="USD" levelOfDetail="Currency" fromDate="20261008" toDate="20261008" endingCash="-17267.98" endingSettledCash="-16343.68"/>'
    '</CashReport>'
)
POSITION = '<OpenPosition symbol="ASTS" position="190" markPrice="56.93" positionValue="10816.7" costBasisPrice="60.24" currency="USD" reportDate="20261008"/>'


def _xml(body: str) -> str:
    return (
        '<?xml version="1.0"?><FlexQueryResponse><FlexStatements><FlexStatement accountId="U1">'
        + body
        + "</FlexStatement></FlexStatements></FlexQueryResponse>"
    )


def _run_import(body: str):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db: Session = _tenant_session(engine)
    result = IBKRImportService().import_flex_xml(db, _xml(body))
    cash = {c.currency: c for c in db.query(CashBalance).all()}
    positions = db.query(Position).count()
    db.close()
    return result, cash, positions


def test_cash_report_currency_imports_real_currencies_only():
    result, cash, positions = _run_import(CASH + POSITION)
    assert set(cash) == {"EUR", "USD"}  # sin BASE_SUMMARY ni polvo de AED
    assert cash["EUR"].balance == Decimal("7433.60")
    assert cash["USD"].balance == Decimal("-17267.98")  # margen: saldo negativo real
    assert cash["USD"].settled_cash == Decimal("-16343.68")
    assert cash["EUR"].as_of.isoformat() == "2026-10-08"  # toDate, no hoy
    assert result["cash_imported"] == 2
    assert result["rows_skipped"] == 0
    assert positions == 1


def test_reimport_updates_cash_without_duplicates():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db: Session = _tenant_session(engine)
    service = IBKRImportService()
    service.import_flex_xml(db, _xml(CASH))
    service.import_flex_xml(db, _xml(CASH.replace("7433.60", "7500.00")))
    rows = db.query(CashBalance).filter(CashBalance.currency == "EUR").all()
    db.close()
    assert len(rows) == 1 and rows[0].balance == Decimal("7500.00")


def test_blank_flex_tenant_env_is_none():
    assert Settings(ibkr_flex_tenant_id="").ibkr_flex_tenant_id is None
    assert Settings(ibkr_flex_tenant_id="1").ibkr_flex_tenant_id == 1


def _client(monkeypatch, responses):
    client = IBKRFlexClient()
    client.settings = Settings(ibkr_flex_token="SECRET-TOKEN", ibkr_flex_query_id="1614243")
    client.poll_delay_seconds = 0
    calls = []

    async def fake_get(url, params, timeout):
        calls.append(url)
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(client, "_get", fake_get)
    return client, calls


def test_statement_retries_while_generating(monkeypatch):
    pending = '<FlexStatementResponse><Status>Warn</Status><ErrorCode>1019</ErrorCode><ErrorMessage>Statement generation in progress</ErrorMessage></FlexStatementResponse>'
    client, calls = _client(monkeypatch, [pending, pending, "<FlexQueryResponse/>"])
    assert asyncio.run(client.fetch_statement("REF")) == "<FlexQueryResponse/>"
    assert len(calls) == 3


def test_statement_permanent_error_does_not_retry(monkeypatch):
    bad = '<FlexStatementResponse><Status>Fail</Status><ErrorCode>1012</ErrorCode><ErrorMessage>Token has expired</ErrorMessage></FlexStatementResponse>'
    client, calls = _client(monkeypatch, [bad])
    with pytest.raises(IBKRFlexError, match="1012"):
        asyncio.run(client.fetch_statement("REF"))
    assert len(calls) == 1


def test_http_error_message_never_contains_token():
    client = IBKRFlexClient()
    client.settings = Settings(ibkr_flex_token="SECRET-TOKEN", ibkr_flex_query_id="1614243")

    class Boom:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, params=None):
            request = httpx.Request("GET", url, params=params)
            raise httpx.HTTPStatusError("boom", request=request, response=httpx.Response(500, request=request))

    import app.services.connectors.ibkr as module
    original = module.httpx.AsyncClient
    module.httpx.AsyncClient = Boom
    try:
        with pytest.raises(IBKRFlexError) as info:
            asyncio.run(client.request_statement())
    finally:
        module.httpx.AsyncClient = original
    assert "SECRET-TOKEN" not in str(info.value)
    assert info.value.__cause__ is None


from datetime import date, timedelta

ACCT = "U1"


def _fresh(body: str, *, account: str = ACCT, days_ago: int = 1, wrap: bool = True) -> str:
    """Extracto con toDate reciente y secciones OpenPositions/CashReport."""
    d = (date.today() - timedelta(days=days_ago)).strftime("%Y%m%d")
    body = body.replace("20261008", d)
    if wrap and "<OpenPositions>" not in body and "<OpenPosition " in body:
        body = body.replace("<OpenPosition ", "<OpenPositions><OpenPosition ", 1)
        body = body[: body.rindex("/>") + 2] + "</OpenPositions>" + body[body.rindex("/>") + 2 :]
    return (
        '<?xml version="1.0"?><FlexQueryResponse><FlexStatements>'
        f'<FlexStatement accountId="{account}" fromDate="{d}" toDate="{d}">'
        + body
        + "</FlexStatement></FlexStatements></FlexQueryResponse>"
    )


def _seeded(source: str = "ibkr_flex"):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db: Session = _tenant_session(engine)
    service = IBKRImportService()
    old = (
        '<OpenPosition symbol="NVDA" position="4" markPrice="190" positionValue="760" costBasisPrice="100" currency="USD" reportDate="20261001"/>'
        '<CashReportCurrency currency="GBP" endingCash="50.00" reportDate="20261001"/>'
    )
    service.import_flex_xml(db, _xml(old + POSITION))
    for row in db.query(Position).all():
        row.source = source
    for row in db.query(CashBalance).all():
        row.source = source
    db.commit()
    return db, service


def _tickers(db):
    from app.models import Company

    names = {c.id: c.ticker for c in db.query(Company).all()}
    return sorted(names[p.company_id] for p in db.query(Position).all())


def _rc(service, db, xml, **kw):
    kw.setdefault("expected_account_id", ACCT)
    kw.setdefault("query_complete_attested", True)
    return service.import_flex_xml(db, xml, reconcile=True, **kw)


def test_reconcile_closes_ibkr_positions_and_cash_missing_from_proven_statement():
    db, service = _seeded()
    result = _rc(service, db, _fresh(CASH + POSITION))
    assert result["reconcile_blocked"] == []
    assert _tickers(db) == ["ASTS"]
    assert result["positions_closed"] == ["NVDA"]
    assert result["cash_removed"] == ["GBP"]
    db.close()


def test_reconcile_requires_expected_account():
    db, service = _seeded()
    with pytest.raises(Exception, match="expected_account_id"):
        service.import_flex_xml(db, _fresh(CASH + POSITION), reconcile=True)
    db.close()


def test_reconcile_never_deletes_manual_or_other_sources():
    db, service = _seeded(source="manual")
    result = _rc(service, db, _fresh(CASH + POSITION))
    assert _tickers(db) == ["ASTS", "NVDA"]
    assert result["positions_closed"] == [] and result["cash_removed"] == []
    db.close()


def test_reconcile_sources_must_be_explicit_to_close_other_sources():
    db, service = _seeded(source="ibkr_screenshot_x")
    _rc(service, db, _fresh(CASH + POSITION))
    assert "NVDA" in _tickers(db)
    _rc(service, db, _fresh(CASH + POSITION), reconcile_sources=("ibkr_flex", "ibkr_screenshot_x"))
    assert _tickers(db) == ["ASTS"]
    db.close()


@pytest.mark.parametrize(
    "xml,reason",
    [
        (lambda: _fresh(POSITION), "CashReport"),
        (lambda: _fresh(CASH), "OpenPositions"),
    ],
)
def test_reconcile_blocked_without_completeness_proof_keeps_everything(xml, reason):
    db, service = _seeded()
    result = _rc(service, db, xml())
    assert result["reconcile_blocked"], reason
    assert any(reason.lower() in r.lower() for r in result["reconcile_blocked"]), result["reconcile_blocked"]
    assert _tickers(db) == ["ASTS", "NVDA"]
    assert result["positions_closed"] == [] and result["cash_removed"] == []
    db.close()


def test_default_import_keeps_absent_positions():
    db, service = _seeded()
    service.import_flex_xml(db, _xml(CASH + POSITION))
    assert _tickers(db) == ["ASTS", "NVDA"]
    db.close()


def test_reconcile_skips_when_any_position_row_was_rejected():
    db, service = _seeded()
    bad = '<OpenPosition symbol="TSLA" markPrice="1" positionValue="1" reportDate="20261008"/>'
    result = _rc(service, db, _fresh(CASH + POSITION + bad))
    assert "NVDA" in _tickers(db)
    assert result["positions_closed"] == []
    assert result["reconcile_blocked"]
    db.close()


def test_dry_run_reports_plan_and_changes_nothing():
    db, service = _seeded()
    result = _rc(service, db, _fresh(CASH + POSITION), dry_run=True)
    assert result["status"] == "dry_run"
    assert result["would_close_positions"] == ["NVDA"]
    assert result["would_remove_cash"] == ["GBP"]
    assert _tickers(db) == ["ASTS", "NVDA"]
    assert {c.currency for c in db.query(CashBalance).all()} >= {"GBP"}
    db.close()


def test_flex_server_error_text_is_never_reflected(monkeypatch):
    client = IBKRFlexClient()
    bad = (
        '<FlexStatementResponse><Status>Fail</Status><ErrorCode>1012</ErrorCode>'
        '<ErrorMessage>Bad token SYNTHETIC-SECRET https://x/?t=SYNTHETIC-SECRET</ErrorMessage></FlexStatementResponse>'
    )

    async def fake_get(self, url, params, timeout):
        return bad

    monkeypatch.setattr(IBKRFlexClient, "_get", fake_get)
    monkeypatch.setattr(client.settings, "ibkr_flex_token", "SYNTHETIC-SECRET")
    monkeypatch.setattr(client.settings, "ibkr_flex_query_id", "1")
    for make in (lambda: client.request_statement(), lambda: client.fetch_statement("REF")):
        with pytest.raises(IBKRFlexError) as info:
            asyncio.run(make())
        assert "SYNTHETIC-SECRET" not in str(info.value)
        assert "Bad token" not in str(info.value)
        assert "1012" in str(info.value)


def test_wrong_account_or_old_statement_is_rejected_before_any_write():
    for xml in (_fresh(CASH + POSITION, account="U2"), _fresh(CASH + POSITION, days_ago=30)):
        db, service = _seeded()
        before = db.query(Position).count()
        with pytest.raises(Exception, match="rechazado"):
            service.import_flex_xml(db, xml, expected_account_id=ACCT)  # incluso sin reconcile
        db.rollback()
        assert db.query(Position).count() == before
        asts = [p for p in db.query(Position).all()]
        assert all(p.source == "ibkr_flex" for p in asts)
        db.close()


def test_reconcile_blocked_without_query_attestation():
    db, service = _seeded()
    result = _rc(service, db, _fresh(CASH + POSITION), query_complete_attested=False)
    assert any("declarada como completa" in r for r in result["reconcile_blocked"])
    assert _tickers(db) == ["ASTS", "NVDA"]
    db.close()


@pytest.mark.parametrize(
    "xml",
    [
        lambda: _fresh(CASH + POSITION, account="U2"),
        lambda: _fresh(CASH + POSITION, days_ago=30),
        lambda: _fresh(CASH + POSITION, days_ago=-3),
        lambda: _fresh(CASH + POSITION).replace('toDate="', 'x="'),
        lambda: _fresh(CASH + POSITION).replace(
            "</FlexStatement>", '</FlexStatement><FlexStatement accountId="U1"/>'
        ),
        lambda: _fresh(CASH + POSITION).replace("<OpenPosition ", '<OpenPosition accountId="U9" ', 1),
    ],
)
def test_identity_failures_reject_before_any_write(xml):
    db, service = _seeded()
    with pytest.raises(Exception, match="rechazado"):
        _rc(service, db, xml())
    db.rollback()
    assert _tickers(db) == ["ASTS", "NVDA"]
    db.close()


@pytest.mark.parametrize(
    "row",
    [
        '<Trades><Trade accountId="U2" tradeID="FOREIGN1" symbol="ZETA" quantity="1" tradePrice="1" tradeDate="20261008" buySell="BUY"/></Trades>',
        '<CashTransactions><CashTransaction accountId="U2" transactionID="FOREIGN2" type="Dividends" amount="5" currency="USD" symbol="ASTS" dateTime="20261008"/></CashTransactions>',
        '<CashReport><CashReportCurrency accountId="U2" currency="EUR" endingCash="1"/></CashReport>',
        '<CashReport accountId="U2" currency="EUR" endingCash="1"/>',
    ],
)
def test_foreign_account_rows_of_any_type_reject_before_any_write(row):
    from app.models import Transaction

    db, service = _seeded()
    xml = _fresh(CASH + POSITION).replace("</FlexStatement>", row + "</FlexStatement>")
    before_tx = db.query(Transaction).count()
    with pytest.raises(Exception, match="rechazado"):
        service.import_flex_xml(db, xml, expected_account_id=ACCT)
    db.rollback()
    assert db.query(Transaction).count() == before_tx
    assert _tickers(db) == ["ASTS", "NVDA"]
    db.close()
