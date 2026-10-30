"""A Flex Query whose Trades section is Order-level only no longer imports nothing silently.

With Trades > Options = «Orders», IBKR exports <Order> rows and no <Trade>
(execution) row. The import returned status ``imported`` with zero trades and
no notice: every buy and sell vanished without a word.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Tenant, Transaction
from app.services.ibkr_import_service import IBKRImportService

ORDER = (
    '<Order accountId="U1" currency="USD" assetCategory="STK" symbol="AAPL" isin="US0378331005" '
    'listingExchange="NASDAQ" tradeDate="20240301" dateTime="20240301;100000" quantity="10" '
    'tradePrice="150" ibCommission="-1" buySell="BUY" ibOrderID="777" tradeID="" levelOfDetail="ORDER"/>'
)
TRADE = (
    '<Trade accountId="U1" currency="USD" assetCategory="STK" symbol="AAPL" isin="US0378331005" '
    'listingExchange="NASDAQ" tradeDate="20240301" quantity="10" tradePrice="150" buySell="BUY" '
    'ibOrderID="777" tradeID="T-1" levelOfDetail="EXECUTION"/>'
)


def _flex(*rows):
    return (
        '<FlexQueryResponse><FlexStatements count="1"><FlexStatement accountId="U1"><Trades>'
        + "".join(rows)
        + "</Trades></FlexStatement></FlexStatements></FlexQueryResponse>"
    )


@pytest.fixture
def db(monkeypatch):
    monkeypatch.setattr("app.services.company_enrichment_service.CompanyEnrichmentService.enrich", lambda *a: False)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        tenant = Tenant(external_id="flex-order-level", name="Fixture")
        session.add(tenant)
        session.flush()
        session.info["tenant_id"] = tenant.id
        yield session


def _level_notices(result):
    return [e for e in result["row_errors"] if "Execution" in e]


def test_order_only_flex_warns_instead_of_importing_nothing_silently(db):
    result = IBKRImportService().import_flex_xml(db, _flex(ORDER))
    notices = _level_notices(result)
    assert len(notices) == 1
    assert "1 fila(s)" in notices[0] and "orden" in notices[0]
    # Orders are not turned into trades (a later execution-level import would duplicate them).
    assert db.query(Transaction).count() == 0


def test_backfill_warns_too(db):
    result = IBKRImportService().import_flex_xml(db, _flex(ORDER), trades_only=True)
    assert len(_level_notices(result)) == 1


def test_execution_rows_beside_orders_import_once_without_notice(db):
    result = IBKRImportService().import_flex_xml(db, _flex(TRADE, ORDER))
    assert _level_notices(result) == []
    rows = db.query(Transaction).all()
    assert [(r.action, float(r.quantity), float(r.price)) for r in rows] == [("buy", 10.0, 150.0)]
