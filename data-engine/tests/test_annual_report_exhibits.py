"""Anexos que son el informe anual: 40-F (EX-99.x) y 10-K (EX-13) (fuentes-1, 8-nov-2026).

BN presenta un 40-F cuyo documento principal es la portada; el informe anual
(estados, MD&A, segmentos) va en EX-99.2 y el AIF en EX-99.1. Antes la tesis
solo pedia el texto del documento principal y el desglose por partes de los
expertos rechazaba BN por falta de ingresos por segmento.
"""

from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import delete, select

from app.core.database import SessionLocal, init_db
from app.models import Company, Document
from app.models.entities import DocumentChunk
from app.services import annual_report_exhibits as are
from app.services.thesis_evidence_service import ThesisEvidenceService

# Filas reales del indice del 40-F de BN (0001001085-26-000006, 18-mar-2026).
BN_INDEX = """<table class="tableFile" summary="Document Format Files">
<tr><th>Seq</th><th>Description</th><th>Document</th><th>Type</th><th>Size</th></tr>
<tr><td>1</td><td>40-F</td><td><a href="/Archives/edgar/data/1001085/000100108526000006/bn-20251231.htm">bn-20251231.htm</a> &nbsp;&nbsp;iXBRL</td><td>40-F</td><td>1064676</td></tr>
<tr><td>2</td><td>EX-99.1</td><td><a href="x">a2025-40xfex991aif.htm</a></td><td>EX-99.1</td><td>1263940</td></tr>
<tr><td>3</td><td>EX-99.2</td><td><a href="x">bn-20251231_d2.htm</a> &nbsp;&nbsp;iXBRL</td><td>EX-99.2</td><td>6550216</td></tr>
<tr><td>4</td><td>EX-99.3</td><td><a href="x">a2025-40xfex993ceocert.htm</a></td><td>EX-99.3</td><td>11914</td></tr>
<tr><td>8</td><td>EX-99.7</td><td><a href="x">a2025-40xfex997deloitte.htm</a></td><td>EX-99.7</td><td>3161</td></tr>
<tr><td>&nbsp;</td><td>Complete submission text file</td><td><a href="x">0001001085-26-000006.txt</a></td><td>&nbsp;</td><td>45547242</td></tr>
<tr><td>9</td><td>XBRL TAXONOMY EXTENSION SCHEMA DOCUMENT</td><td><a href="x">bn-20251231.xsd</a></td><td>EX-101.SCH</td><td>234615</td></tr>
</table>"""

BASE = "https://www.sec.gov/Archives/edgar/data/1001085/000100108526000006/"
BN_40F = {
    "form": "40-F", "filing_date": "2026-03-18", "accession_number": "0001001085-26-000006",
    "report_date": "2025-12-31", "index_url": BASE, "document_url": BASE + "bn-20251231.htm",
}


def test_indice_da_los_anexos_grandes_del_informe_mayor_primero():
    rows = are.parse_report_exhibits(BN_INDEX)
    assert [(r["type"], r["filename"]) for r in rows] == [
        ("EX-99.2", "bn-20251231_d2.htm"), ("EX-99.1", "a2025-40xfex991aif.htm"),
    ]
    # Certificaciones y consentimiento del auditor (3-12 KB) fuera; EX-101 no es informe.
    assert are.index_page_url(BN_40F) == BASE + "0001001085-26-000006-index.html"


def test_ex13_de_un_10k_cuenta():
    html = BN_INDEX.replace("EX-99.2", "EX-13")
    assert [r["type"] for r in are.parse_report_exhibits(html)][0] == "EX-13"


@contextmanager
def _company(db, ticker):
    old = db.scalar(select(Company).where(Company.ticker == ticker))
    if old is not None:
        _cleanup(db, old.id)
    company = Company(
        ticker=ticker, name=f"anexos {ticker}", exchange="NYSE", currency="USD", sector="Financials",
        industry="Test", company_type="holding", valuation_model="unassigned",
        special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    try:
        yield company
    finally:
        _cleanup(db, company.id)


def _cleanup(db, company_id):
    doc_ids = select(Document.id).where(Document.company_id == company_id)
    db.execute(delete(DocumentChunk).where(DocumentChunk.document_id.in_(doc_ids)))
    db.execute(delete(Document).where(Document.company_id == company_id))
    db.execute(delete(Company).where(Company.id == company_id))
    db.commit()


def test_40f_encola_el_texto_de_sus_anexos_informe(monkeypatch):
    init_db()
    db = SessionLocal()
    queued: list[tuple[str, str, str | None]] = []
    exhibits = [{**r, "url": BASE + r["filename"]} for r in are.parse_report_exhibits(BN_INDEX)]
    monkeypatch.setattr(ThesisEvidenceService, "_fetch_filings", lambda self, cik: [dict(BN_40F)])
    monkeypatch.setattr(ThesisEvidenceService, "_fetch_annual_report_exhibits", lambda self, f: list(exhibits))
    monkeypatch.setattr(
        ThesisEvidenceService, "_enqueue_annual_report_text",
        lambda self, db, company, filing: queued.append(
            (filing["form"], filing["document_url"], filing.get("parent_form"))),
    )
    try:
        with _company(db, "ANEXOS40F") as company:
            result = ThesisEvidenceService()._ingest_filings(db, company, "0001001085")
            db.commit()
            annual = result["annual_report"]
            assert annual["form"] == "40-F" and annual["status"] == "queued"
            assert queued == [
                ("40-F EX-99.2", BASE + "bn-20251231_d2.htm", "40-F"),
                ("40-F EX-99.1", BASE + "a2025-40xfex991aif.htm", "40-F"),
                ("40-F", BASE + "bn-20251231.htm", None),
            ]
            assert [(e["type"], e["text"]) for e in annual["exhibits"]] == [("EX-99.2", "queued"), ("EX-99.1", "queued")]
            # Con el texto del EX-99.2 ya troceado no se vuelve a pedir.
            doc = Document(company_id=company.id, title="40-F EX-99.2", source_type="SEC",
                           source_url=BASE + "bn-20251231_d2.htm", metadata_={"form": "40-F EX-99.2"})
            db.add(doc)
            db.flush()
            db.add(DocumentChunk(document_id=doc.id, chunk_index=0, text="Segmented results", token_count=2))
            db.commit()
            queued.clear()
            again = ThesisEvidenceService()._ingest_filings(db, company, "0001001085")
            assert [(e["type"], e["text"]) for e in again["annual_report"]["exhibits"]] == [
                ("EX-99.2", "ingested"), ("EX-99.1", "queued")]
            assert ("40-F EX-99.2", BASE + "bn-20251231_d2.htm", "40-F") not in queued
    finally:
        db.close()


def test_un_20f_no_pide_indice():
    called: list[str] = []
    svc = ThesisEvidenceService()
    svc._fetch_annual_report_exhibits = lambda f: called.append(f["form"]) or []  # type: ignore[method-assign]
    assert svc._annual_report_exhibits(None, None, {**BN_40F, "form": "20-F"}) == []  # type: ignore[arg-type]
    assert called == []
