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


def test_cash_transaction_codes_stay_out_of_user_notes():
    db = _session()
    _imported_trade(db, _xml(
        '<CashTransactions><CashTransaction accountId="U1" symbol="AAPL" currency="USD" '
        'type="Dividends" amount="12" dateTime="20261002" transactionID="C-1" notes="R"/>'
        '</CashTransactions>'
    ))
    row = db.scalars(select(Transaction)).one()
    assert "notes" not in row.raw_payload
    assert row.raw_payload["ibkr_notes"] == "R"


def test_corporate_action_codes_stay_out_of_user_notes():
    db = _session()
    _imported_trade(db, _xml(
        '<CorporateActions><CorporateAction accountId="U1" symbol="AAPL" currency="USD" '
        'type="DIV" amount="5" dateTime="20261002" transactionID="CA-1" notes="Po"/>'
        '</CorporateActions>'
    ))
    row = db.scalars(select(Transaction)).one()
    assert "notes" not in row.raw_payload
    assert row.raw_payload["ibkr_notes"] == "Po"


def test_cancel_pair_codes_stay_out_of_user_notes():
    db = _session()
    # Un par operacion/anulacion crea DOS filas: sin el helper de una sola.
    result = IBKRImportService().import_flex_xml(db, _xml(
        '<Trades>'
        '<Trade accountId="U1" symbol="AAPL" assetCategory="STK" currency="USD" '
        'buySell="BUY" quantity="10" tradePrice="11.2" tradeDate="20261001" '
        'tradeID="T-6" ibCommission="-0.1" notes="O"/>'
        '<Trade accountId="U1" symbol="AAPL" assetCategory="STK" currency="USD" '
        'buySell="BUY (Ca.)" quantity="-10" tradePrice="11.2" tradeDate="20261001" '
        'tradeID="T-6C" ibCommission="0.1" notes="Ca"/>'
        '</Trades>'
    ))
    assert result["status"] == "imported", result
    rows = {t.external_id: t for t in db.scalars(select(Transaction)).all()}
    assert "notes" not in rows["T-6C"].raw_payload
    assert rows["T-6C"].raw_payload["ibkr_notes"] == "Ca"


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


def test_user_authored_note_marker_is_never_suppressed():
    # Caso limite del auditor: el usuario escribe "P" como nota en una fila de
    # broker y la edita; el marcador de autoria la protege para siempre.
    payload = _payload_for({"tradeID": "T-1", "notes": "P", "notes_author": "user"})
    assert payload["notes"] == "P"
    assert payload["ibkr_note_codes"] is None


def test_user_authored_note_marker_coexists_with_broker_codes():
    payload = _payload_for({
        "tradeID": "T-1", "ibkr_notes": "O", "notes": "P", "notes_author": "user",
    })
    assert payload["notes"] == "P"
    assert payload["ibkr_note_codes"] == ["O"]


# --- Contrato HTTP real (response_model): el campo llega al wire ------------

from uuid import uuid4

from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import Portfolio, Tenant
from tests.auth_helpers import auth_settings, signed_request

SECRET = "ibkr-broker-notes-test-secret-----"


def _wire_client(monkeypatch):
    monkeypatch.setattr(
        auth_module, "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET),
    )
    init_db()
    tenant_ext = f"ibkr-notes-{uuid4().hex[:8]}"
    db = SessionLocal()
    db.add(Tenant(external_id=tenant_ext, name="IBKR notes wire test"))
    db.commit()
    db.close()
    return TestClient(main.app), tenant_ext, "ibkr-notes-user"


def _seed_broker_row(tenant_ext: str) -> tuple[str, int]:
    db = SessionLocal()
    tenant_row = db.query(Tenant).filter(Tenant.external_id == tenant_ext).one()
    db.info["tenant_id"] = tenant_row.id
    db.add(Portfolio(name="Main", base_currency="EUR", is_default=True))
    # Ticker unico por test: companies.ticker tiene unicidad global.
    ticker = f"W{uuid4().hex[:6].upper()}"
    company = Company(
        ticker=ticker, name="Wire Co", exchange="BME", currency="EUR",
        sector="Tech", industry="I", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.flush()
    tx = Transaction(
        company_id=company.id, trade_date=date(2026, 1, 15), action="buy",
        quantity=Decimal("100"), price=Decimal("10"), fees=Decimal("1"),
        currency="EUR",
        # Fila historica de broker: codigo de maquina volcado en "notes".
        raw_payload={"tradeID": "T-1", "notes": "P"},
    )
    db.add(tx)
    db.commit()
    tx_id = tx.id
    db.close()
    return ticker, tx_id


def test_wire_get_serves_codes_not_user_notes(monkeypatch):
    client, tenant, user = _wire_client(monkeypatch)
    _seed_broker_row(tenant)
    res = signed_request(client, SECRET, tenant, user, "GET", "/api/portfolio/transactions")
    assert res.status_code == 200, res.text
    item = res.json()["items"][0]
    # response_model: sin declarar el campo en el schema se perdia en el wire.
    assert item["notes"] is None
    assert item["ibkr_note_codes"] == ["P"]


def test_wire_post_marks_user_note_authorship(monkeypatch):
    client, tenant, user = _wire_client(monkeypatch)
    res = signed_request(
        client, SECRET, tenant, user, "POST", "/api/portfolio/transactions",
        json_body={
            "ticker": "WIRE", "action": "buy", "quantity": "5", "price": "10",
            "trade_date": "2026-01-15", "currency": "EUR", "notes": "P",
        },
    )
    assert res.status_code == 201, res.text
    # Nota genuina del usuario aunque sea un codigo de la leyenda.
    assert res.json()["notes"] == "P"
    assert res.json()["ibkr_note_codes"] is None


def test_wire_put_fixes_legacy_hidden_user_note(monkeypatch):
    # Escenario del auditor: fila historica con nota de usuario "P" oculta;
    # tras editarla por PUT queda marcada como del usuario y se sirve.
    client, tenant, user = _wire_client(monkeypatch)
    ticker, tx_id = _seed_broker_row(tenant)
    res = signed_request(
        client, SECRET, tenant, user, "PUT", f"/api/portfolio/transactions/{tx_id}",
        json_body={
            "ticker": ticker, "action": "buy", "quantity": "100", "price": "10",
            "trade_date": "2026-01-15", "currency": "EUR", "notes": "P",
        },
    )
    assert res.status_code == 200, res.text
    assert res.json()["notes"] == "P"
    res = signed_request(client, SECRET, tenant, user, "GET", "/api/portfolio/transactions")
    assert res.json()["items"][0]["notes"] == "P"
