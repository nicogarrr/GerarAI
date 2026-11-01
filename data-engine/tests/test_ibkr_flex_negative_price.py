"""Flex de IBKR: una operación con precio negativo se omite con aviso.

Antes la fila llegaba a la base de datos y el CHECK ``price >= 0`` tumbaba la
importación entera (y cada sincronización automática siguiente) con un
IntegrityError, sin decir qué fila era.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Tenant, Transaction
from app.services.ibkr_import_service import IBKRImportService, validate_flex_xml

XML = """<?xml version="1.0" encoding="UTF-8"?>
<FlexQueryResponse queryName="test">
  <FlexStatements>
    <FlexStatement accountId="U123456">
      <Trade symbol="AAPL" tradeID="T1" buySell="BUY" quantity="10" tradePrice="150" tradeDate="2026-06-01" currency="USD"/>
      <Trade symbol="MSFT" tradeID="T2" buySell="BUY" quantity="5" tradePrice="-0.35" tradeDate="2026-06-02" currency="USD"/>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>"""


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    tenant = Tenant(external_id="ibkr-neg", name="IBKR neg")
    db.add(tenant)
    db.flush()
    db.info["tenant_id"] = tenant.id
    return db


def test_validador_senala_el_precio_negativo():
    errors = validate_flex_xml(XML)
    assert any("MSFT" in e and "negativo" in e for e in errors)


def test_importacion_omite_la_fila_y_guarda_el_resto():
    with _session() as db:
        result = IBKRImportService().import_flex_xml(db, XML)
        assert result["status"] == "imported"
        assert result["trades_imported"] == 1
        assert result["rows_skipped"] == 1
        assert any("negativo" in e for e in result["row_errors"])
        assert [t.external_id for t in db.query(Transaction).all()] == ["T1"]
