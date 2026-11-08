"""Informes de emisoras sin SEC (fuentes-1, 8-nov-2026): NSM de la FCA o web de inversores.

Fairfax (FFH.TO) y Georgia Capital (CGEO.L) no presentan a la SEC: antes la
tesis se quedaba en «Sin CIK no hay filings» y el desglose por partes no tenía
ningún documento que citar. SEDAR+ bloquea con captcha (Radware), así que en
Canadá se usa la página de inversores de la empresa.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import delete, select

from app.core.database import SessionLocal, init_db
from app.models import Company, Document
from app.models.entities import DocumentChunk
from app.services import issuer_reports
from app.services.connectors.fca_nsm import parse_search_hits
from app.services.thesis_evidence_service import ThesisEvidenceService

FIXTURES = Path(__file__).parent / "fixtures"
BASE = "https://www.fairfax.ca/investors/"


def test_fairfax_ultimo_anual_y_ultimo_trimestral_en_ingles():
    html = (FIXTURES / "fairfax_investors_links.html").read_text()
    links = {l.kind: l for l in issuer_reports.pick_ir_reports(html, BASE)}
    assert links["annual"].url == "https://www.fairfax.ca/wp-content/uploads/2026/03/FFH_Fairfax-Financial-2025-Annual-Report-144860.pdf"
    assert links["annual"].date == "2026-03"
    assert links["periodic"].url == "https://www.fairfax.ca/wp-content/uploads/2026/11/FFH-2026-Q3-Interim-Report-Final-Z3yjaS825R.pdf"
    assert links["periodic"].source == "web de la empresa (www.fairfax.ca)"


def test_version_francesa_y_circulares_fuera():
    html = ('<a href="/wp-content/uploads/2027/03/FFH-2026-Annual-Report-French.pdf">Rapport</a>'
            '<a href="/wp-content/uploads/2027/04/Management-Proxy-Circular-2027.pdf">Circular</a>'
            '<a href="/wp-content/uploads/2026/03/Annual-Report-2025.pdf">Annual Report 2025</a>')
    links = issuer_reports.pick_ir_reports(html, BASE)
    assert [(l.kind, l.url.rsplit("/", 1)[-1]) for l in links] == [("annual", "Annual-Report-2025.pdf")]


def _hit(ftype, fmt, day, link):
    return {"_id": link, "_source": {"lei": "213800Q65T5GNBOW7H65", "company": "Georgia Capital PLC", "type": ftype,
                                      "document_format": fmt, "submitted_date": f"{day}T07:00:00Z",
                                      "download_link": link, "disclosure_id": link}}


GC = parse_search_hits({"hits": {"hits": [
    _hit("3rd Quarter Results", "Plain text", "2026-10-28", "NSM/RNS/0df1db8b.html"),
    _hit("Half-year Financial Report", "Plain text", "2026-08-04", "NSM/RNS/03beb4a4.html"),
    _hit("Annual Financial Report", "Untagged", "2026-04-24", "NSM/DirectUpload/NI-000143657/x.xhtml"),
    _hit("Annual Financial Report", "Plain text", "2026-04-23", "NSM/RNS/21b45652.html"),
    _hit("Final Results", "Plain text", "2026-02-26", "NSM/RNS/final2025.html"),
    _hit("Transaction in Own Shares", "Plain text", "2026-11-06", "NSM/RNS/tios.html"),
]}})


def test_georgia_capital_resultados_anuales_y_ultimo_trimestre_del_nsm():
    links = {l.kind: l for l in issuer_reports.pick_nsm_reports(GC)}
    # El anuncio de resultados (texto completo con el NAV) gana al aviso «Annual Financial Report».
    assert links["annual"].url == "https://data.fca.org.uk/artefacts/NSM/RNS/final2025.html"
    assert links["periodic"].url == "https://data.fca.org.uk/artefacts/NSM/RNS/0df1db8b.html"
    assert links["periodic"].date == "2026-10-28"


@contextmanager
def _company(db, ticker):
    old = db.scalar(select(Company).where(Company.ticker == ticker))
    if old is not None:
        _cleanup(db, old.id)
    company = Company(ticker=ticker, name="Fairfax Financial Holdings", exchange="TSX", currency="CAD",
                      sector="Financials", industry="Insurance", company_type="insurer", valuation_model="unassigned",
                      special_sources=[], special_risks=[], factor_tags=[], ir_url=BASE)
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


def test_sin_cik_la_tesis_encola_los_informes_del_emisor(monkeypatch):
    html = (FIXTURES / "fairfax_investors_links.html").read_text()
    links = issuer_reports.pick_ir_reports(html, BASE)
    queued: list[tuple[str, str]] = []
    monkeypatch.setattr(ThesisEvidenceService, "_fetch_non_sec_reports", lambda self, company: (links, "ok"))
    monkeypatch.setattr(ThesisEvidenceService, "_enqueue_report",
                        lambda self, db, company, link, published: queued.append((link.kind, link.url)))
    init_db()
    db = SessionLocal()
    try:
        with _company(db, "FFHTEST.TO") as company:
            result = ThesisEvidenceService()._ingest_filings(db, company, None)
            assert result["status"] == "pending"  # SEC sigue sin datos, y se dice
            reports = result["non_sec_reports"]
            assert reports["status"] == "ok"
            assert [(i["kind"], i["text"]) for i in reports["items"]] == [("annual", "queued"), ("periodic", "queued")]
            assert queued[0][1].endswith("FFH_Fairfax-Financial-2025-Annual-Report-144860.pdf")
    finally:
        db.close()
