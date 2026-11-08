"""Los códigos Flex del bróker (notes="O", "C;P"...) no son notas del usuario.

El importador Flex vuelca TODOS los atributos XML en raw_payload; entre ellos
viaja notes="O"/"C;P"/"Ca": códigos de la leyenda oficial del extracto
(https://www.ibkrguides.com/reportingreference/reportguide/codes_default.htm:
O = Opening Trade, P = Partial Execution, C = Closing Trade, Ca = Cancelled).
La API de movimientos servía raw_payload["notes"] como nota del usuario y el
front la pintaba tal cual: una "P" a pelo en Cartera > Movimientos.

Reglas fijadas aquí:
- importación Flex nueva: el atributo notes del XML se conserva como
  raw_payload["ibkr_notes"] (prueba fiscal intacta) y NUNCA en "notes", que es
  el campo del usuario (el alta/edición manual escriben ahí).
- filas ya importadas (códigos en raw_payload["notes"]): la API no las sirve
  como nota del usuario; las expone como ``ibkr_note_codes``.
- una nota real del usuario se sigue sirviendo verbatim, tenga la fila
  identidad de bróker o no.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import create_engine, select

from app.api.routes.portfolio import _transaction_payload
from app.core.database import Base
from app.models import Company, Transaction
from app.services.ibkr_import_service import IBKRImportService
from tests.test_ibkr_import import _tenant_session


def _session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return _tenant_session(engine)


def _xml(*rows):
    return (
        '<?xml version="1.0"?><FlexQueryResponse><FlexStatements><FlexStatement accountId="U1">'
        + "".join(rows)
        + "</FlexStatement></FlexStatements></FlexQueryResponse>"
    )


def _imported_trade(db, xml):
    result = IBKRImportService().import_flex_xml(db, xml)
    assert result["status"] == "imported", result
    return db.scalars(select(Transaction)).one()


def _payload_for(raw_payload):
    now = datetime.now(UTC)
    tx = Transaction(
        trade_date=date(2026, 10, 26), action="buy",
        quantity=Decimal("1"), price=Decimal("10"), fees=Decimal("0"),
        currency="USD", raw_payload=raw_payload,
        created_at=now, updated_at=now,
    )
    return _transaction_payload(tx, Company(ticker="ACME", name="Acme"))


def test_flex_import_moves_broker_codes_out_of_user_notes():
    db = _session()
    trade = _imported_trade(db, _xml(
        '<Trades><Trade accountId="U1" symbol="AAPL" assetCategory="STK" currency="USD" '
        'buySell="BUY" quantity="5" tradePrice="100" tradeDate="20261001" '
        'tradeID="T-1" ibCommission="-1" notes="O"/></Trades>'
    ))
    assert "notes" not in trade.raw_payload
    assert trade.raw_payload["ibkr_notes"] == "O"


def test_flex_import_moves_combined_codes_on_cash_and_corporate_rows():
    db = _session()
    _imported_trade(db, _xml(
        '<CashTransactions><CashTransaction accountId="U1" symbol="AAPL" currency="USD" '
        'type="Dividends" amount="12" dateTime="20261002" transactionID="C-1" notes="R"/>'
        '</CashTransactions>'
    ))
    row = db.scalars(select(Transaction)).one()
    assert "notes" not in row.raw_payload
    assert row.raw_payload["ibkr_notes"] == "R"


def test_legacy_row_with_broker_codes_is_not_served_as_user_note():
    payload = _payload_for({"tradeID": "T-1", "notes": "C;P"})
    assert payload["notes"] is None
    assert payload["ibkr_note_codes"] == ["C", "P"]


def test_legacy_row_single_code_partial_execution():
    # El caso visto por QA: una "P" a pelo (Partial Execution, leyenda oficial).
    payload = _payload_for({"ibExecID": "E-9", "notes": "P"})
    assert payload["notes"] is None
    assert payload["ibkr_note_codes"] == ["P"]


def test_new_import_serves_codes_only_under_ibkr_note_codes():
    payload = _payload_for({"tradeID": "T-1", "ibkr_notes": "Ca"})
    assert payload["notes"] is None
    assert payload["ibkr_note_codes"] == ["Ca"]


def test_user_note_on_manual_row_is_served_verbatim():
    payload = _payload_for({"notes": "compra familiar"})
    assert payload["notes"] == "compra familiar"
    assert payload["ibkr_note_codes"] is None


def test_user_text_on_broker_row_is_not_confused_with_codes():
    payload = _payload_for({"tradeID": "T-1", "notes": "regalo de mi madre"})
    assert payload["notes"] == "regalo de mi madre"
    assert payload["ibkr_note_codes"] is None


def test_user_note_and_broker_codes_coexist_after_edit():
    # Edición sobre una fila importada nueva: nota del usuario en "notes",
    # códigos del bróker conservados en "ibkr_notes".
    payload = _payload_for({"tradeID": "T-1", "ibkr_notes": "O", "notes": "revisar plusvalía"})
    assert payload["notes"] == "revisar plusvalía"
    assert payload["ibkr_note_codes"] == ["O"]
