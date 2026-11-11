"""FRE/DE totales de gestoras que el XBRL no etiqueta: tabla anual del HTML del mismo informe anual (BN 40-F 2025).

Fixture: ``bn-20251231_d2.htm`` real (40-F 2025 de Brookfield, accession 0001001085-26-000006) recortado a sus
tablas 7, 26 y 58, más la tabla 0 de la nota de prensa del 2T 2026 (trimestre y últimos doce meses) como señuelo.
"""
from __future__ import annotations

import asyncio
import copy
import gzip
import json
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, Document, FinancialFact
from app.services import filing_html_tables as ft
from app.services import financial_ingestion_service as ingestion
from app.services import sec_extension_facts as sx
from app.services.financial_ingestion_service import FinancialIngestionService

FIX = Path(__file__).parent / "fixtures" / "xbrl_extensions"
BN_ACCN, BN_CIK = "0001001085-26-000006", "0001001085"
BN_INDEX = [("0001001085-26-000006-index.html", None), ("a2025-40xfex991aif.htm", 1263940),
            ("a2025-40xfex993ceocert.htm", 11914), ("bn-20251231.htm", 1064676), ("bn-20251231_d2.htm", 6550216),
            ("bn-20251231.xsd", 234615), ("bn-20251231_lab.xml", 1), ("bn-20251231_cal.xml", 1),
            ("bn-20251231_htm.xml", 1), ("R1.htm", 89569), ("ex10_28.htm", 50000),
            ("kkr-20251231xex211subsidia.htm", 40000)]


def _read(name: str) -> bytes:
    return gzip.decompress((FIX / f"{name}.gz").read_bytes())


def test_lector_toma_solo_columnas_anuales_con_escala_y_etiqueta_exacta():
    doc = _read("bn-20251231_d2_de.htm")
    found = ft.resolve(doc, ["distributable_earnings", "fee_related_earnings"], source="bn-20251231_d2.htm")
    de, fre = found["distributable_earnings"], found["fee_related_earnings"]
    assert de.conflict is None and fre.conflict is None
    assert de.values == {("2025-01-01", "2025-12-31"): Decimal(6_008_000_000),
                         ("2024-01-01", "2024-12-31"): Decimal(6_274_000_000)}
    assert fre.values == {("2025-01-01", "2025-12-31"): Decimal(2_995_000_000),
                          ("2024-01-01", "2024-12-31"): Decimal(2_456_000_000)}
    # El señuelo (tres meses y últimos doce meses del 2T 2026, 1.548 / 6.172) nunca entra como anual.
    assert all(c.end.endswith("-12-31") for c in ft.read_annual_rows(doc))
    # «Distributable earnings before realizations» y las partes por segmento no son el total.
    assert not ft.ROW_RULES[0].matches("Distributable earnings before realizations 3")
    assert ft.ROW_RULES[0].matches("Distributable earnings 3")


def test_tablas_que_no_casan_dan_conflicto_y_sin_escala_no_hay_cifra():
    t = ("<table><tr><td>For the years ended Dec. 31 (millions)</td></tr><tr><td></td><td>2025</td></tr>"
         "<tr><td>Distributable earnings</td><td>100</td></tr></table>")
    otra = t.replace(">100<", ">101<")
    assert ft.resolve(t + otra, ["distributable_earnings"], source="x")["distributable_earnings"].conflict
    sin_escala = t.replace(" (millions)", "")
    assert ft.resolve(sin_escala, ["distributable_earnings"], source="x") == {}
    negativo = t.replace(">100<", ">(12<").replace("</td></tr></table>", "</td><td>)</td></tr></table>")
    got = ft.resolve(negativo, ["distributable_earnings"], source="x")["distributable_earnings"].values
    assert got == {("2025-01-01", "2025-12-31"): Decimal(-12_000_000)}


def test_documentos_html_del_filing_principal_primero_sin_visor_ni_certificados():
    assert sx.html_report_documents(BN_INDEX, "bn-20251231.htm") == [
        "bn-20251231.htm", "bn-20251231_d2.htm", "a2025-40xfex991aif.htm"]


def _flow(val, year):
    return {"fy": 2025, "fp": "FY", "form": "40-F", "start": f"{year}-01-01", "end": f"{year}-12-31",
            "val": val, "filed": "2026-03-18", "accn": BN_ACCN}


class _FakeBN:
    fetched: list[str] = []

    async def cik_for_ticker(self, ticker, entity_name=None):
        return BN_CIK

    async def annual_report_anchors(self, cik_):
        return {BN_ACCN: "2025-12-31"}

    async def index_accessions(self, cik_):
        return {BN_ACCN}

    async def submissions(self, cik_):
        return {"sic": "6282", "filings": {"recent": {
            "form": ["40-F"], "accessionNumber": [BN_ACCN], "filingDate": ["2026-03-18"],
            "reportDate": ["2025-12-31"], "primaryDocument": ["bn-20251231.htm"], "isXBRL": [1]}}}

    async def company_facts(self, cik_):
        return {"cik": int(BN_CIK), "entityName": "Brookfield Corp", "facts": {"ifrs-full": copy.deepcopy({
            "Revenue": {"units": {"USD": [_flow(75_000_000_000, 2025)]}},
            "Assets": {"units": {"USD": [{**_flow(500_000_000_000, 2025), "start": None}]}}})}}

    async def filing_document(self, url):
        _FakeBN.fetched.append(url)
        name = url.rsplit("/", 1)[-1]
        if name == "index.json":
            return json.dumps({"directory": {"item": [{"name": n, "size": "" if s is None else str(s)}
                                                      for n, s in BN_INDEX]}}).encode(), "application/json"
        if name == "bn-20251231_d2.htm":
            return _read("bn-20251231_d2_de.htm"), "text/html"
        if name in ("bn-20251231.htm", "a2025-40xfex991aif.htm"):
            return b"<html><body><p>sin tablas</p></body></html>", "text/html"
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


def test_ingesta_sec_bn_de_total_desde_la_tabla_del_informe_anual(db, monkeypatch):
    _FakeBN.fetched = []
    monkeypatch.setattr(ingestion, "SECClient", _FakeBN)
    company = Company(ticker="BN", name="Brookfield Corporation", exchange="NYSE", currency="USD",
                      sector="Financials", industry="Asset management and holdings", company_type="research_candidate",
                      valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[])
    db.add(company)
    db.commit()
    asyncio.run(FinancialIngestionService().refresh_from_sec(db=db, company=company))
    de = _facts(db, company, "distributable_earnings")
    assert float(de[2025].value) == pytest.approx(6_008_000_000)
    assert float(de[2024].value) == pytest.approx(6_274_000_000)
    meta = db.scalars(select(Document).where(Document.company_id == company.id)).first().metadata_["sec_extension_map"]
    m = meta["metrics"]["distributable_earnings"]
    assert m["rule"] == "tabla_html" and m["source_url"].endswith("/bn-20251231_d2.htm")
    assert meta["resolver"] == sx.RESOLVER_VERSION
    # El documento grande se lee una sola vez y el visor R*.htm nunca.
    assert sum(u.endswith("/bn-20251231_d2.htm") for u in _FakeBN.fetched) == 1
    assert not any(u.endswith("/R1.htm") for u in _FakeBN.fetched)

    # Segundo refresh del mismo accession: se reutiliza sin red.
    _FakeBN.fetched = []
    monkeypatch.setattr(ingestion, "SEC_INGESTION_RULES_VERSION", 999)
    asyncio.run(FinancialIngestionService().refresh_from_sec(db=db, company=company))
    assert not any(u.endswith(".htm") for u in _FakeBN.fetched)
    assert float(_facts(db, company, "distributable_earnings")[2025].value) == pytest.approx(6_008_000_000)


def test_resolucion_de_version_anterior_se_rehace():
    assert sx.RESOLVER_VERSION >= 2
