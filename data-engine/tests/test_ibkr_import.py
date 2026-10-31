"""Tests for the IBKR Flex import pipeline (IBKRImportService)."""
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import CashBalance, Company, Position, Tenant, Transaction
from app.services.ibkr_import_service import IBKRImportError, IBKRImportService, validate_flex_xml

SAMPLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<FlexQueryResponse queryName="test">
  <FlexStatements>
    <FlexStatement accountId="U123456">
      <OpenPosition symbol="AAPL" position="10" markPrice="180.5" positionValue="1805" costBasisPrice="150" currency="USD" reportDate="2026-08-20"/>
      <OpenPosition symbol="MSFT" position="5" markPrice="400" positionValue="2000" costBasisPrice="350" currency="USD" reportDate="2026-08-20"/>
      <CashReport currency="USD" endingCash="1234.56" settledCash="1000" reportDate="2026-08-20"/>
      <Trade symbol="AAPL" tradeID="T1" buySell="BUY" quantity="10" tradePrice="150" ibCommission="1" tradeDate="2026-06-01" currency="USD"/>
      <CashTransaction type="Dividends" trxID="D1" amount="15.5" dateTime="2026-07-01" currency="USD"/>
      <CashTransaction type="Other Fees" trxID="F1" amount="-3.2" dateTime="2026-07-02" currency="USD"/>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>"""


def _tenant_session(engine) -> Session:
    db = Session(engine)
    tenant = db.query(Tenant).filter_by(external_id="ibkr-test").first()
    if tenant is None:
        tenant = Tenant(external_id="ibkr-test", name="IBKR test")
        db.add(tenant)
        db.flush()
    db.info["tenant_id"] = tenant.id
    return db


def test_import_flex_xml_creates_positions_cash_and_transactions():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with _tenant_session(engine) as db:
        result = IBKRImportService().import_flex_xml(db, SAMPLE_XML)

        assert result["status"] == "imported"
        assert result["positions_imported"] == 2
        assert result["cash_imported"] == 1
        assert result["trades_imported"] == 1
        assert result["dividends_imported"] == 1
        assert result["fees_imported"] == 1
        assert result["portfolio_snapshot_id"] is not None

        assert db.query(Position).count() == 2
        assert db.query(CashBalance).count() == 1
        assert db.query(Transaction).count() == 3
        assert db.query(Company).count() == 2

        aapl = db.query(Company).filter_by(ticker="AAPL").one()
        position = db.query(Position).filter_by(company_id=aapl.id).one()
        assert position.quantity == Decimal("10")
        assert position.average_cost == Decimal("150")
        assert position.market_value == Decimal("1805")
        assert position.source == "ibkr_flex"

        trade = db.query(Transaction).filter_by(external_id="T1").one()
        assert trade.action == "buy"
        assert trade.price == Decimal("150")
        assert trade.fees == Decimal("1")

        dividend = db.query(Transaction).filter_by(external_id="D1").one()
        assert dividend.action == "dividend"
        assert dividend.company_id is None


def test_reimport_is_idempotent_by_external_id():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with _tenant_session(engine) as db:
        first = IBKRImportService().import_flex_xml(db, SAMPLE_XML)
        second = IBKRImportService().import_flex_xml(db, SAMPLE_XML)

        assert first["trades_imported"] == 1
        assert second["trades_imported"] == 0
        assert second["dividends_imported"] == 0
        assert second["fees_imported"] == 0
        assert db.query(Transaction).count() == 3
        assert db.query(Position).count() == 2


def test_import_creates_unknown_companies_as_placeholders():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    xml = SAMPLE_XML.replace("symbol=\"AAPL\"", "symbol=\"ZZZZ\"")
    with _tenant_session(engine) as db:
        IBKRImportService().import_flex_xml(db, xml)
        company = db.query(Company).filter_by(ticker="ZZZZ").one()
        assert company.company_type == "imported_holding"
        assert "IBKR" in company.special_sources
        assert company.currency == "USD"

MISSING_DATE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<FlexQueryResponse queryName="test">
  <FlexStatements>
    <FlexStatement accountId="U123456">
      <Trade symbol="AAPL" tradeID="T-NODATE" buySell="BUY" quantity="10" tradePrice="150" ibCommission="1" currency="USD"/>
      <CashTransaction type="Dividends" trxID="D-NODATE" amount="15.5" currency="USD"/>
      <CorporateAction type="DIV" transactionID="C-NODATE" symbol="AAPL" amount="20" currency="USD"/>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>"""


def test_rows_without_dates_are_skipped_never_dated_today():
    # A fabricated date.today() on a money record would poison the FIFO tax
    # ledger: rows with no usable date are skipped, not invented.
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with _tenant_session(engine) as db:
        result = IBKRImportService().import_flex_xml(db, MISSING_DATE_XML)

        assert result["trades_imported"] == 0
        assert result["dividends_imported"] == 0
        assert result["rows_skipped"] == 3
        assert db.query(Transaction).count() == 0


def test_external_id_dedupe_is_one_query_for_many_trades():
    # Re-import dedupe must be one batched IN query, not one SELECT per row.
    from sqlalchemy import event

    trades = "\n      ".join(
        f'<Trade symbol="AAPL" tradeID="BT{i}" buySell="BUY" quantity="1" '
        f'tradePrice="150" ibCommission="0" tradeDate="2026-06-01" currency="USD"/>'
        for i in range(10)
    )
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<FlexQueryResponse queryName="test">
  <FlexStatements>
    <FlexStatement accountId="U123456">
      {trades}
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>"""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with _tenant_session(engine) as db:
        first = IBKRImportService().import_flex_xml(db, xml)
        assert first["trades_imported"] == 10

        statements = []

        def listener(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        event.listen(db.get_bind(), "before_cursor_execute", listener)
        try:
            second = IBKRImportService().import_flex_xml(db, xml)
        finally:
            event.remove(db.get_bind(), "before_cursor_execute", listener)

        assert second["trades_imported"] == 0  # all deduped
        batched = [s for s in statements if "external_id IN" in s]
        per_row = [s for s in statements if "external_id = ?" in s]
        assert len(batched) == 1
        assert per_row == []


def test_flex_decimal_dot_is_always_the_decimal_separator():
    from decimal import Decimal

    from app.services.ibkr_import_service import _decimal

    # Regresion: "32.725" (precio real de ZETA) se leia como 32725 (agrupacion es-ES).
    assert _decimal("32.725") == Decimal("32.725")
    assert _decimal("42.935") == Decimal("42.935")
    assert _decimal("-0.362219321") == Decimal("-0.362219321")
    assert _decimal("1250") == Decimal("1250")
    # Con coma o con dos puntos siguen valiendo las notaciones localizadas.
    assert _decimal("1,234.56") == Decimal("1234.56")
    assert _decimal("1.234,56") == Decimal("1234.56")
    assert _decimal("1.234.567") == Decimal("1234567")


BOMB_XML = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE lolz [
 <!ENTITY lol "lollollollollollollollollollol">
 <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
 <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">
]>
<FlexQueryResponse queryName="bomb">
  <FlexStatements>
    <FlexStatement accountId="&lol3;">
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>"""


def test_validate_flex_xml_rejects_entities():
    """Un XML con DOCTYPE/entidades (billion laughs) se rechaza sin expandir."""
    errors = validate_flex_xml(BOMB_XML)
    assert errors
    assert "entidades" in errors[0]


def test_import_flex_xml_rejects_entities():
    """El import tambien rechaza entidades con error controlado (no 500, no expansion)."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with _tenant_session(engine) as db:
        with pytest.raises(IBKRImportError, match="entidades"):
            IBKRImportService().import_flex_xml(db, BOMB_XML)
