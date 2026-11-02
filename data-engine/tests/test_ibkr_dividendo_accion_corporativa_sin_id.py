"""Un dividendo que llega como CorporateAction sin transactionID no se duplica al reimportar.

CashTransaction y Trade ya usan un id estable de respaldo cuando la query Flex no
trae la columna de id; CorporateAction (DIV/PD/PI) no: cada sync volvía a apuntar
el mismo dividendo (dos cobros de 12 en vez de uno) e inflaba el informe fiscal.
"""

from app.models import Transaction
from app.services.ibkr_import_service import IBKRImportService
from tests.test_ibkr_reimport_without_ids import BUY, _rows, _session, _xml

CA_DIV = (
    '<CorporateAction accountId="U1" symbol="AAPL" currency="USD" type="DIV" '
    'amount="12" dateTime="20261002" description="AAPL CASH DIVIDEND"/>'
)


def _dividends(db):
    return [r for r in _rows(db) if r[0] == "dividend"]


def test_corporate_action_dividend_without_id_is_not_duplicated_on_reimport():
    db = _session()
    xml = _xml(f"<Trades>{BUY}</Trades><CorporateActions>{CA_DIV}</CorporateActions>")
    first = IBKRImportService().import_flex_xml(db, xml)
    second = IBKRImportService().import_flex_xml(db, xml)
    assert first["dividends_imported"] == 1
    assert second["dividends_imported"] == 0
    assert len(_dividends(db)) == 1


def test_two_identical_corporate_action_dividends_in_one_file_stay_two():
    db = _session()
    xml = _xml(f"<Trades>{BUY}</Trades><CorporateActions>{CA_DIV}{CA_DIV}</CorporateActions>")
    for _ in range(2):
        IBKRImportService().import_flex_xml(db, xml)
    assert len(_dividends(db)) == 2


def test_corporate_action_dividend_stored_before_without_id_is_adopted():
    db = _session()
    xml = _xml(f"<Trades>{BUY}</Trades><CorporateActions>{CA_DIV}</CorporateActions>")
    IBKRImportService().import_flex_xml(db, xml)
    for t in db.query(Transaction).all():  # como las guardaba la versión anterior
        t.external_id = None
    db.commit()
    IBKRImportService().import_flex_xml(db, xml)
    assert len(_dividends(db)) == 1
    assert all(t.external_id for t in db.query(Transaction).all())


def test_corporate_action_dividend_with_id_keeps_its_id():
    db = _session()
    with_id = CA_DIV.replace("/>", ' transactionID="777"/>')
    xml = _xml(f"<Trades>{BUY}</Trades><CorporateActions>{with_id}</CorporateActions>")
    for _ in range(2):
        IBKRImportService().import_flex_xml(db, xml)
    dividends = [t for t in db.query(Transaction).all() if t.action == "dividend"]
    assert [t.external_id for t in dividends] == ["777"]
