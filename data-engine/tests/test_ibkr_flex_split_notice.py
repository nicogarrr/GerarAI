"""Flex splits (and other share-count corporate actions) are not dropped silently.

A CorporateAction row of type FS/RS/SD/SO was skipped with no trace, in the
normal import and in the backfill. The ledger then kept pre-split quantities
and the tax FIFO ended in an over-sell with nothing telling the user why.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Tenant, Transaction
from app.services.ibkr_import_service import IBKRImportService

TRADE = (
    '<Trade symbol="NVDA" isin="US67066G1040" listingExchange="NASDAQ" currency="USD" buySell="BUY" '
    'quantity="10" tradePrice="1000" tradeDate="20240301" tradeID="NV-1"/>'
)
SPLIT = (
    '<CorporateAction symbol="NVDA" isin="US67066G1040" type="FS" reportDate="20240610" '
    'quantity="90" description="NVDA(US67066G1040) SPLIT 10 FOR 1" transactionID="NV-FS-1"/>'
)


def _flex(*rows):
    return "<FlexQueryResponse><FlexStatement>" + "".join(rows) + "</FlexStatement></FlexQueryResponse>"


@pytest.fixture
def db(monkeypatch):
    monkeypatch.setattr("app.services.company_enrichment_service.CompanyEnrichmentService.enrich", lambda *a: False)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        tenant = Tenant(external_id="flex-split", name="Fixture")
        session.add(tenant)
        session.flush()
        session.info["tenant_id"] = tenant.id
        yield session


def _split_notices(result):
    return [e for e in result["row_errors"] if "FS" in e and "NVDA" in e]


def test_flex_split_row_is_reported_not_dropped(db):
    result = IBKRImportService().import_flex_xml(db, _flex(TRADE, SPLIT))
    assert len(_split_notices(result)) == 1
    assert "Acciones corporativas" in _split_notices(result)[0]
    # Nothing is invented in the ledger: the trade stays, no split leg is written.
    assert [t.action for t in db.query(Transaction).all()] == ["buy"]


def test_backfill_reports_the_split_too(db):
    result = IBKRImportService().import_flex_xml(db, _flex(TRADE, SPLIT), trades_only=True)
    assert len(_split_notices(result)) == 1


def test_dividend_corporate_actions_unchanged(db):
    result = IBKRImportService().import_flex_xml(
        db,
        _flex(TRADE, '<CorporateAction symbol="NVDA" type="DIV" dateTime="20240627" amount="0.10" '
              'currency="USD" transactionID="NV-DIV-1"/>'),
    )
    assert not [e for e in result["row_errors"] if "Acción corporativa" in e]
    assert result["dividends_imported"] == 1
