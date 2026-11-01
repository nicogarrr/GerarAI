"""Equipo de expertos: una cifra sacada de un filing de la SEC enlaza al filing.

Antes la fuente de «Estados financieros» solo decía «filing» y no llevaba
enlace, así que en «Fuentes» no se podía abrir el 10-K del que salía la
cifra. Ahora lleva la URL del archivo SEC (la del documento guardado o, si
solo hay accession, la del índice del filing en EDGAR). Una página de un
proveedor que no es archivo SEC no se enlaza. SQLite en memoria, sin red.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, Document, FinancialFact
from app.services.expert_team import RunContext, build_tools
from app.services.expert_team.chat import _source_label

SEC_URL = "https://www.sec.gov/Archives/edgar/data/789019/000095017025100235/msft-20250630.htm"


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        msft = Company(ticker="MSFT", name="Microsoft", exchange="NASDAQ", currency="USD", cik="0000789019",
                       company_type="operating", valuation_model="dcf")
        session.add(msft)
        session.flush()
        sec_doc = Document(tenant_id=1, company_id=msft.id, title="MSFT 10-K 2025", source_type="sec_filing",
                           source_url=SEC_URL)
        vendor_doc = Document(tenant_id=1, company_id=msft.id, title="Proveedor", source_type="provider",
                              source_url="https://example.com/msft/financials")
        session.add_all([sec_doc, vendor_doc])
        session.flush()

        def fact(year, metric, **kw):
            return FinancialFact(tenant_id=1, company_id=msft.id, metric=metric, value=Decimal(100), unit="USD",
                                 period="FY", fiscal_year=year, is_reported=True, **kw)

        session.add_all([
            fact(2025, "revenue", source_type="sec_filing", source_id=sec_doc.id),
            fact(2024, "revenue", source_type="sec_companyfacts", accession_number="0000950170-24-087843"),
            fact(2024, "net_income", source_type="provider", source_id=vendor_doc.id),
        ])
        session.commit()
        yield session


def _facts(db):
    return build_tools(db)["financial_facts"].fn(RunContext(tenant_id=1, ticker="MSFT"))


def test_fact_from_a_saved_sec_document_links_to_it(db):
    by_year = {(o.source["date"], o.source["filing"].split(":")[0]): o.source for o in _facts(db)}
    assert by_year[("2025", "sec_filing")]["url"] == SEC_URL


def test_fact_with_only_an_accession_links_to_the_edgar_index(db):
    by_kind = {o.source["filing"].split(":")[0]: o.source for o in _facts(db)}
    assert by_kind["sec_companyfacts"]["url"] == (
        "https://www.sec.gov/Archives/edgar/data/789019/000095017024087843/0000950170-24-087843-index.htm"
    )


def test_non_sec_page_is_not_linked(db):
    by_kind = {o.source["filing"].split(":")[0]: o.source for o in _facts(db)}
    assert not by_kind["provider"].get("url")


def test_sec_source_label_says_sec(db):
    by_kind = {o.source["filing"].split(":")[0]: o.source for o in _facts(db)}
    assert "SEC" in _source_label(by_kind["sec_filing"], "es")
    assert "SEC" in _source_label(by_kind["sec_companyfacts"], "en")
    assert "SEC" not in _source_label(by_kind["provider"], "es")
