"""Plan B de la SEC: el último 20-F/40-F/10-K que companyfacts no trae se lee de su instancia XBRL.

Antes (main): TSMC presentó su 20-F de 2025 el 16-abr-2026 (accession 0001628280-26-025362), pero
companyfacts solo tenía su portada (dei), sin un hecho IFRS: la app valoraba TSM con 2024. Ahora se lee
``tsm-20251231_htm.xml`` (el XBRL extraído que EDGAR publica con el filing) con las mismas reglas.
"""

import asyncio

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, Document, FinancialFact
from app.services import financial_ingestion_service as ingestion
from app.services.connectors import sec_filing_instance as fin
from app.services.financial_ingestion_service import FinancialIngestionService

K24, K25 = "0001193125-25-083423", "0001628280-26-025362"

INSTANCE = b"""<?xml version="1.0" encoding="utf-8"?>
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:ifrs-full="https://xbrl.ifrs.org/taxonomy/2024-03-27/ifrs-full"
  xmlns:dei="http://xbrl.sec.gov/dei/2024" xmlns:iso4217="http://www.xbrl.org/2003/iso4217"
  xmlns:xbrldi="http://xbrl.org/2006/xbrldi" xmlns:tsm="http://www.tsmc.com/20251231" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <xbrli:context id="FY25"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0001046179</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:startDate>2025-01-01</xbrli:startDate><xbrli:endDate>2025-12-31</xbrli:endDate></xbrli:period></xbrli:context>
  <xbrli:context id="FY24"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0001046179</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:startDate>2024-01-01</xbrli:startDate><xbrli:endDate>2024-12-31</xbrli:endDate></xbrli:period></xbrli:context>
  <xbrli:context id="I25"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0001046179</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:instant>2025-12-31</xbrli:instant></xbrli:period></xbrli:context>
  <xbrli:context id="FY25seg"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0001046179</xbrli:identifier>
    <xbrli:segment><xbrldi:explicitMember dimension="ifrs-full:SegmentsAxis">tsm:WaferMember</xbrldi:explicitMember></xbrli:segment></xbrli:entity>
    <xbrli:period><xbrli:startDate>2025-01-01</xbrli:startDate><xbrli:endDate>2025-12-31</xbrli:endDate></xbrli:period></xbrli:context>
  <xbrli:unit id="twd"><xbrli:measure>iso4217:TWD</xbrli:measure></xbrli:unit>
  <xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>
  <xbrli:unit id="shares"><xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unit>
  <ifrs-full:RevenueFromContractsWithCustomers contextRef="FY25" unitRef="twd" decimals="-6">3809054000000</ifrs-full:RevenueFromContractsWithCustomers>
  <ifrs-full:RevenueFromContractsWithCustomers contextRef="FY24" unitRef="twd" decimals="-6">2894307700000</ifrs-full:RevenueFromContractsWithCustomers>
  <ifrs-full:RevenueFromContractsWithCustomers contextRef="FY25seg" unitRef="twd" decimals="-6">3000000000000</ifrs-full:RevenueFromContractsWithCustomers>
  <ifrs-full:ProfitLossAttributableToOwnersOfParent contextRef="FY25" unitRef="twd" decimals="-6">1697604000000</ifrs-full:ProfitLossAttributableToOwnersOfParent>
  <ifrs-full:ProfitLossAttributableToOwnersOfParent contextRef="FY25" unitRef="usd" decimals="-5">54115500000</ifrs-full:ProfitLossAttributableToOwnersOfParent>
  <ifrs-full:CashAndCashEquivalents contextRef="I25" unitRef="twd" decimals="-6">2767856400000</ifrs-full:CashAndCashEquivalents>
  <ifrs-full:AdjustedWeightedAverageShares contextRef="FY25" unitRef="shares" decimals="-5">25930600000</ifrs-full:AdjustedWeightedAverageShares>
  <tsm:SomethingIssuerSpecific contextRef="FY25" unitRef="twd" decimals="-6">1</tsm:SomethingIssuerSpecific>
</xbrli:xbrl>"""


def _flow(val, year, accn, filed, fy, form="20-F"):
    return {"fy": fy, "fp": "FY", "form": form, "start": f"{year}-01-01", "end": f"{year}-12-31",
            "val": val, "filed": filed, "accn": accn}


COMPANYFACTS = {"cik": 1046179, "entityName": "Taiwan Semiconductor Manufacturing Co., Ltd.", "facts": {
    "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [
        {"end": "2025-12-31", "val": 25932000000, "accn": K25, "fy": 2025, "fp": "FY", "form": "20-F", "filed": "2026-04-16"}]}}},
    "ifrs-full": {
        "RevenueFromContractsWithCustomers": {"units": {"TWD": [_flow(2_894_307_700_000, 2024, K24, "2025-04-17", 2024)]}},
        "ProfitLossAttributableToOwnersOfParent": {"units": {"TWD": [_flow(1_173_268_000_000, 2024, K24, "2025-04-17", 2024)]}},
        "Assets": {"units": {"TWD": [{**_flow(6_691_938_000_000, 2024, K24, "2025-04-17", 2024), "start": None}]}},
    }}}

SUBMISSIONS = {"filings": {"recent": {
    "form": ["6-K", "20-F", "20-F"], "accessionNumber": ["0001046179-26-000728", K25, K24],
    "filingDate": ["2026-10-22", "2026-04-16", "2025-04-17"], "reportDate": ["", "2025-12-31", "2024-12-31"],
    "primaryDocument": ["x.htm", "tsm-20251231.htm", "d896993d20f.htm"], "isXBRL": [0, 1, 1]}}}


class _FakeSECTsmc:
    fetched: list[str] = []

    async def cik_for_ticker(self, ticker, entity_name=None):
        return "0001046179"

    async def annual_report_anchors(self, cik):
        return {K24: "2024-12-31", K25: "2025-12-31"}

    async def index_accessions(self, cik):
        return {K24, K25}

    async def submissions(self, cik):
        return SUBMISSIONS

    async def company_facts(self, cik):
        import copy

        return copy.deepcopy(COMPANYFACTS)

    async def filing_document(self, url):
        _FakeSECTsmc.fetched.append(url)
        return INSTANCE, "application/xml"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def test_parse_instance_solo_estandar_sin_dimensiones_y_una_divisa():
    parsed = fin.parse_instance(INSTANCE, accn=K25, form="20-F", filed="2026-04-16", fiscal_year=2025)
    assert set(parsed) == {"ifrs-full"}  # sin extensiones del emisor
    rev = parsed["ifrs-full"]["RevenueFromContractsWithCustomers"]["units"]["TWD"]
    assert [(e["end"], e["val"]) for e in rev] == [("2025-12-31", 3809054000000), ("2024-12-31", 2894307700000)]
    ni = parsed["ifrs-full"]["ProfitLossAttributableToOwnersOfParent"]["units"]
    assert set(ni) == {"TWD"}  # la traducción de conveniencia a USD no entra
    assert fin.instance_name("tsm-20251231.htm") == "tsm-20251231_htm.xml"
    assert fin.accessions_in(COMPANYFACTS) == {K24}


def test_tsm_20f_2025_entra_por_la_instancia(db, monkeypatch):
    monkeypatch.setattr(ingestion, "SECClient", _FakeSECTsmc)
    company = Company(ticker="TSM", name="Taiwan Semiconductor Manufacturing Co., Ltd.", exchange="NYSE",
                      currency="USD", sector="Technology", industry="Semiconductors",
                      company_type="research_candidate", valuation_model="unassigned",
                      special_sources=[], special_risks=[], factor_tags=[])
    db.add(company)
    db.commit()
    asyncio.run(FinancialIngestionService().refresh_from_sec(db=db, company=company))
    rev = {f.fiscal_year: float(f.value) for f in db.scalars(select(FinancialFact).where(
        FinancialFact.company_id == company.id, FinancialFact.metric == "revenue")) if f.fiscal_quarter == "FY"}
    assert rev.get(2025) == pytest.approx(3_809_054_000_000)
    assert rev.get(2024) == pytest.approx(2_894_307_700_000)
    assert _FakeSECTsmc.fetched[-1].endswith(f"/1046179/{K25.replace('-', '')}/tsm-20251231_htm.xml")
    doc = db.scalars(select(Document).where(Document.company_id == company.id)).first()
    assert (doc.metadata_ or {}).get("sec_filing_instance", {}).get("accession") == K25


def test_sin_filing_pendiente_no_se_descarga_nada():
    sub = {"filings": {"recent": {"form": ["20-F"], "accessionNumber": [K24], "filingDate": ["2025-04-17"],
                                  "reportDate": ["2024-12-31"], "primaryDocument": ["a.htm"], "isXBRL": [1]}}}
    assert fin.latest_annual_missing(sub, {K24}, {"20-F"}) is None
