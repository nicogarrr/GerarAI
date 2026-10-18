"""Hermetic tests: shares_outstanding derivado (suma de clases dei ECSO)
para filers multi-clase (META, GOOGL, BRK.B, ASTS, V).

Sin red. Instancia minima con la estructura real de portada EDGAR:
contextos INSTANT con explicitMember de clase.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Company, Document, FinancialFact, Tenant
from app.services.class_filer_eps_service import (
    backfill_class_shares_outstanding,
)

ECSO_XML = """<?xml version="1.0"?>
<xbrl xmlns="http://www.xbrl.org/2003/instance" xmlns:xbrli="http://www.xbrl.org/2003/instance"
      xmlns:dei="http://xbrl.sec.gov/dei/2023" xmlns:m="http://www.example.com/m">
  <unit id="ushares"><measure>xbrli:shares</measure></unit>
  <context id="iA_new"><entity><identifier scheme="s">X</identifier>
    <segment><explicitMember dimension="m:StatementClassOfStockAxis">m:ClassACommonStockMember</explicitMember></segment></entity>
    <period><instant>2025-10-24</instant></period></context>
  <context id="iB_new"><entity><identifier scheme="s">X</identifier>
    <segment><explicitMember dimension="m:StatementClassOfStockAxis">m:ClassBCommonStockMember</explicitMember></segment></entity>
    <period><instant>2025-10-24</instant></period></context>
  <context id="iA_old"><entity><identifier scheme="s">X</identifier>
    <segment><explicitMember dimension="m:StatementClassOfStockAxis">m:ClassACommonStockMember</explicitMember></segment></entity>
    <period><instant>2025-07-31</instant></period></context>
  <context id="iC_consol"><entity><identifier scheme="s">X</identifier></entity>
    <period><instant>2025-10-24</instant></period></context>
  <dei:EntityCommonStockSharesOutstanding contextRef="iA_new" unitRef="ushares">2200000000</dei:EntityCommonStockSharesOutstanding>
  <dei:EntityCommonStockSharesOutstanding contextRef="iB_new" unitRef="ushares">325000000</dei:EntityCommonStockSharesOutstanding>
  <dei:EntityCommonStockSharesOutstanding contextRef="iA_old" unitRef="ushares">2190000000</dei:EntityCommonStockSharesOutstanding>
  <dei:EntityCommonStockSharesOutstanding contextRef="iC_consol" unitRef="ushares">9999999999</dei:EntityCommonStockSharesOutstanding>
</xbrl>
"""

SEGMENT_ECSO_XML = ECSO_XML.replace(
    'dimension="m:StatementClassOfStockAxis"', 'dimension="m:StatementBusinessSegmentsAxis"')


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[Tenant.__table__, Company.__table__, Document.__table__, FinancialFact.__table__],
    )
    with Session(engine) as session:
        yield session


def _company(db: Session, ticker: str = "META") -> Company:
    row = Company(
        ticker=ticker, name=f"{ticker} Inc", exchange="NASDAQ", currency="USD",
        sector="S", industry="I", company_type="operating", valuation_model="standard_dcf",
    )
    db.add(row)
    db.flush()
    return row


def _fake_fetchers(xml: str):
    def fetch_json(url: str) -> dict:
        if "submissions" in url:
            return {"filings": {"recent": {
                "form": ["10-Q", "10-K"],
                "accessionNumber": ["0001-25-000002", "0001-25-000001"]}}}
        return {"directory": {"item": [{"name": "x-20251024_htm.xml"}]}}

    def fetch_bytes(url: str) -> bytes:
        return xml.encode()

    return fetch_json, fetch_bytes


def test_derived_sum_of_latest_instant_per_class(db):
    """Suma A+B del instante mas reciente; el consolidado sin dimension no
    entra (lo cubre companyfacts) y el instante viejo de A se descarta."""
    company = _company(db)
    fetch_json, fetch_bytes = _fake_fetchers(ECSO_XML)
    result = backfill_class_shares_outstanding(
        db, company, cik="1326801", fetch_json=fetch_json, fetch_bytes=fetch_bytes)
    assert result.written is True
    assert result.shares_total == Decimal("2200000000") + Decimal("325000000")
    assert result.members == ("ClassACommonStockMember", "ClassBCommonStockMember")
    assert result.as_of == "2025-10-24"
    row = db.scalar(select(FinancialFact))
    assert row.metric == "shares_outstanding"
    assert row.period == "2025-10-24:DEI"
    assert row.unit == "shares"
    # Derivado documentado, nunca presentado como reportado:
    assert row.is_reported is False and row.source_type == "derived"
    doc = db.scalar(select(Document))
    prov = (doc.metadata_ or {})["class_shares_provenance"]
    assert prov["derivation"] == "sum_of_class_members"
    assert prov["members"]["ClassACommonStockMember"] == "2200000000"
    assert prov["concept"] == "dei:EntityCommonStockSharesOutstanding"


def test_idempotent_second_run(db):
    company = _company(db)
    fetch_json, fetch_bytes = _fake_fetchers(ECSO_XML)
    backfill_class_shares_outstanding(
        db, company, cik="1", fetch_json=fetch_json, fetch_bytes=fetch_bytes)
    second = backfill_class_shares_outstanding(
        db, company, cik="1", fetch_json=fetch_json, fetch_bytes=fetch_bytes)
    assert second.written is False and second.skipped_reason == "ya existe"
    assert len(db.scalars(select(FinancialFact)).all()) == 1


def test_segment_axis_never_sums(db):
    """ECSO por SEGMENTO no son acciones de una clase: no se escribe nada."""
    company = _company(db)
    fetch_json, fetch_bytes = _fake_fetchers(SEGMENT_ECSO_XML)
    result = backfill_class_shares_outstanding(
        db, company, cik="1", fetch_json=fetch_json, fetch_bytes=fetch_bytes)
    assert result.written is False
    assert result.skipped_reason == "sin ECSO dimensionado por clase"
    assert db.scalars(select(FinancialFact)).all() == []
