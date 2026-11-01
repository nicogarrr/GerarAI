"""Flex completo: opciones, futuros y bonos no entran al libro como acciones.

El libro (y el FIFO fiscal) solo sabe de acciones y fondos: coste = cantidad
x precio. En un contrato de opción IBKR da el precio por acción subyacente
(multiplicador 100) y en un bono el precio es un % del nominal, así que
importarlos como compras de acciones apuntaba 1 call AAPL a 5 $ como 5 $ de
coste (eran 500 $), 1.000 de nominal a 99,5 como 99.500 $ (eran 995 $) y la
posición abierta de la opción con coste 5 y valor 600 (+11.900 %). La
importación solo de operaciones ya los saltaba; la completa ahora también,
con un aviso.
"""
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Company, Position, Tenant, Transaction
from app.services.ibkr_import_service import IBKRImportService

FLEX = (
    "<FlexQueryResponse><FlexStatement>"
    '<Trade assetCategory="STK" symbol="AAPL" currency="USD" buySell="BUY" quantity="10" '
    'tradePrice="150" tradeDate="20261020" tradeID="S1"/>'
    '<Trade assetCategory="OPT" symbol="AAPL  261218C00200000" underlyingSymbol="AAPL" multiplier="100" '
    'currency="USD" buySell="BUY" quantity="1" tradePrice="5" tradeDate="20261021" tradeID="O1"/>'
    '<Trade assetCategory="FUT" symbol="ESZ6" underlyingSymbol="ES" multiplier="50" currency="USD" '
    'buySell="BUY" quantity="1" tradePrice="6000" tradeDate="20261021" tradeID="F1"/>'
    '<Trade assetCategory="BOND" symbol="T 4 1/2 11/15/33" currency="USD" buySell="BUY" quantity="1000" '
    'tradePrice="99.5" tradeDate="20261021" tradeID="B1"/>'
    '<OpenPosition assetCategory="OPT" symbol="AAPL  261218C00200000" underlyingSymbol="AAPL" '
    'multiplier="100" currency="USD" position="1" markPrice="6" positionValue="600" costBasisPrice="5" '
    'reportDate="20261028"/>'
    '<OpenPosition assetCategory="STK" symbol="AAPL" currency="USD" position="10" markPrice="160" '
    'positionValue="1600" costBasisPrice="150" reportDate="20261028"/>'
    "</FlexStatement></FlexQueryResponse>"
)


@pytest.fixture
def db(monkeypatch):
    monkeypatch.setattr("app.services.company_enrichment_service.CompanyEnrichmentService.enrich", lambda *a: False)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        tenant = Tenant(external_id="flex-non-share", name="Fixture")
        session.add(tenant)
        session.flush()
        session.info["tenant_id"] = tenant.id
        yield session


def test_full_flex_import_skips_options_futures_and_bonds(db):
    result = IBKRImportService().import_flex_xml(db, FLEX)

    tickers = {company.ticker for company in db.scalars(select(Company))}
    assert tickers == {"AAPL"}
    trades = db.scalars(select(Transaction)).all()
    assert [(t.action, float(t.quantity), float(t.price)) for t in trades] == [("buy", 10.0, 150.0)]
    positions = db.scalars(select(Position)).all()
    assert [(float(p.quantity), float(p.average_cost)) for p in positions] == [(10.0, 150.0)]
    assert result["trades_imported"] == 1
    notices = " ".join(result["row_errors"])
    for symbol in ("AAPL  261218C00200000", "ESZ6", "T 4 1/2 11/15/33"):
        assert symbol in notices
