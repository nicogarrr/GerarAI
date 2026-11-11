"""Plan C de la SEC con linkbases embebidos en el esquema (.xsd) o con otro nombre: BX 10-K 2025.

El 10-K 2025 de Blackstone (accession 0001193125-26-082531, documento principal d48618d10k.htm) no publica
``d48618d10k_lab.xml`` ni ``_cal.xml``: las etiquetas y el cálculo van DENTRO de ``bx-20251231.xsd`` (filings
de Donnelley). Antes la resolución caía en N/D «no se pudo leer lab» y esa N/D se reutilizaba para siempre en
el mismo accession: BX nunca tenía FRE ni DE. Fixtures: el .xsd real recortado a los conceptos de FRE/DE y
sus arcos, y la instancia real recortada a esos hechos.
"""
from __future__ import annotations

import asyncio
import gzip
import json
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, Document, FinancialFact
from app.services import financial_ingestion_service as ingestion
from app.services import sec_extension_facts as sx
from app.services.financial_ingestion_service import FinancialIngestionService

FIX = Path(__file__).parent / "fixtures" / "xbrl_extensions"
BX_ACCN, BX_CIK, BX_STEM = "0001193125-26-082531", "0001393818", "d48618d10k"
BX_INDEX = ["0001193125-26-082531-index.html", "0001193125-26-082531-xbrl.zip", "bx-20251231.xsd",
            "d48618d10k.htm", "d48618d10k_htm.xml", "FilingSummary.xml", "MetaLinks.json", "R1.htm"]


def _read(name: str) -> bytes:
    return gzip.decompress((FIX / f"{name}.gz").read_bytes())


def test_filing_file_names_prefiere_el_propio_luego_cualquiera_luego_el_esquema():
    assert sx.filing_file_names(BX_INDEX, BX_STEM) == {
        "lab": "bx-20251231.xsd", "cal": "bx-20251231.xsd", "instance": "d48618d10k_htm.xml"}
    workiva = ["kkr-20251231.xsd", "kkr-20251231_lab.xml", "kkr-20251231_cal.xml", "kkr-20251231_htm.xml"]
    assert sx.filing_file_names(workiva, "kkr-20251231") == {
        "lab": "kkr-20251231_lab.xml", "cal": "kkr-20251231_cal.xml", "instance": "kkr-20251231_htm.xml"}
    otro = ["x-20251231.xsd", "x-20251231_lab.xml", "d1_htm.xml"]
    assert sx.filing_file_names(otro, "d1") == {"lab": "x-20251231_lab.xml", "cal": "x-20251231.xsd",
                                                 "instance": "d1_htm.xml"}
    # Ambiguo (dos esquemas, ninguna pieza propia): no se adivina.
    assert sx.filing_file_names(["a.xsd", "b.xsd"], "d1") == {}


def _flow(val, year):
    return {"fy": 2025, "fp": "FY", "form": "10-K", "start": f"{year}-01-01", "end": f"{year}-12-31",
            "val": val, "filed": "2026-02-27", "accn": BX_ACCN}


class _FakeBX:
    fetched: list[str] = []

    async def cik_for_ticker(self, ticker, entity_name=None):
        return BX_CIK

    async def annual_report_anchors(self, cik_):
        return {BX_ACCN: "2025-12-31"}

    async def index_accessions(self, cik_):
        return {BX_ACCN}

    async def submissions(self, cik_):
        return {"sic": "6282", "filings": {"recent": {
            "form": ["10-K"], "accessionNumber": [BX_ACCN], "filingDate": ["2026-02-27"],
            "reportDate": ["2025-12-31"], "primaryDocument": [f"{BX_STEM}.htm"], "isXBRL": [1]}}}

    async def company_facts(self, cik_):
        return {"cik": int(BX_CIK), "entityName": "Blackstone Inc.", "facts": {"us-gaap": {
            "Revenues": {"units": {"USD": [_flow(13_000_000_000, 2025)]}},
            "Assets": {"units": {"USD": [{**_flow(45_000_000_000, 2025), "start": None}]}}}}}

    async def filing_document(self, url):
        _FakeBX.fetched.append(url)
        name = url.rsplit("/", 1)[-1]
        if name == "index.json":
            return json.dumps({"directory": {"item": [{"name": n} for n in BX_INDEX]}}).encode(), "application/json"
        if name not in BX_INDEX:
            raise httpx.HTTPStatusError("404", request=httpx.Request("GET", url),
                                        response=httpx.Response(404, request=httpx.Request("GET", url)))
        return _read(name), "application/xml"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _facts(db, company, metric):
    return {f.fiscal_year: f for f in db.scalars(select(FinancialFact).where(
        FinancialFact.company_id == company.id, FinancialFact.metric == metric)) if f.fiscal_quarter == "FY"}


def test_ingesta_sec_bx_fre_y_de_con_linkbases_en_el_esquema(db, monkeypatch):
    _FakeBX.fetched = []
    monkeypatch.setattr(ingestion, "SECClient", _FakeBX)
    company = Company(ticker="BX", name="Blackstone Inc.", exchange="NYSE", currency="USD", sector="Financials",
                      industry="Investment advice (SIC 6282)", company_type="research_candidate",
                      valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[])
    db.add(company)
    db.commit()
    asyncio.run(FinancialIngestionService().refresh_from_sec(db=db, company=company))
    fre, de = _facts(db, company, "fee_related_earnings"), _facts(db, company, "distributable_earnings")
    # Cifras del 10-K 2025 de BX (bx:FeeRelatedEarnings y bx:SegmentDistributableEarnings, total de segmentos).
    assert float(fre[2025].value) == pytest.approx(5_737_537_000)
    assert float(fre[2024].value) == pytest.approx(5_282_065_000)
    assert float(de[2025].value) == pytest.approx(7_882_214_000)
    meta = db.scalars(select(Document).where(Document.company_id == company.id)).first().metadata_["sec_extension_map"]
    assert meta["urls"]["lab"].endswith("/bx-20251231.xsd") and meta["urls"]["cal"].endswith("/bx-20251231.xsd")
    assert meta["metrics"]["fee_related_earnings"]["concept"] == "bx:FeeRelatedEarnings"
    # El esquema se descarga una sola vez para etiquetas y cálculo.
    assert sum(u.endswith("/bx-20251231.xsd") for u in _FakeBX.fetched) == 1


def test_una_nd_por_fallo_de_descarga_no_se_reutiliza():
    cached = {"filing": {"accn": BX_ACCN}, "metrics": {"fee_related_earnings": {
        "metric": "fee_related_earnings", "status": "N/D",
        "motivo": "no se pudo leer lab del filing 0001193125-26-082531 (HTTPStatusError)"}}}
    assert sx._fetch_failed(cached)
    assert sx._fetch_failed({"fetch_error": "lab", "metrics": {}})
    assert not sx._fetch_failed({"metrics": {"fee_related_earnings": {"status": "N/D", "motivo": "sin concepto"}}})
