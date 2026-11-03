"""Motores sectoriales con sus datos propios: informe anual y entradas etiquetadas.

- El informe anual (10-K/20-F/40-F) y el ultimo intermedio entran siempre en
  la seleccion de filings aunque haya muchos 8-K (CB, CPT, KKR) y aunque el
  emisor sea 40-F/6-K (BN); su texto se pide si falta.
- Una ficha de filing (sin texto) ya no bloquea la ingesta del texto.
- Ratio combinado y NOI se extraen del texto del informe anual como hechos NO
  reportados con cita, y el coste del equity sale por CAPM: el motor valora y
  cada uno de esos inputs viaja etiquetado en ``estimated_inputs``.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import delete, select

from app.core.database import SessionLocal, init_db
from app.models import Company, Document, FinancialFact, InferredInput
from app.models.entities import DocumentChunk
from app.services import sector_inputs
from app.services.thesis_evidence_service import ThesisEvidenceService, select_filings
from app.services.valuation_service import ValuationService

CB_TABLE = (
    "A P&C combined ratio under 100 percent indicates underwriting income. 2025 2024 2023 "
    "Combined ratio: Loss and loss expense ratio 59.1 % 60.4 % 60.6 % Policy acquisition cost "
    "ratio 18.6 % 18.1 % 17.8 % Administrative expense ratio 8.0 % 8.1 % 8.1 % P&C Combined "
    "ratio 85.7 % 86.6 % 86.5 % Catastrophe losses (6.3) % (5.5) % (4.5) % P&C CAY combined "
    "ratio excluding catastrophe losses 81.9 % 83.1 % 83.9 %"
)
CPT_TABLE = (
    "The following table presents NOI (in thousands): Year Ended December 31, 2025 2024 "
    "Net income $ 386,000 $ 163,000 Less: Gain on sale of operating properties (260,910) "
    "(43,806) Plus: Income tax expense 4,019 2,926 Net operating income $ 1,006,834 $ 985,037 "
    "Property-Level NOI"
)


def _filing(form: str, date: str, n: int) -> dict:
    return {
        "form": form,
        "filing_date": date,
        "accession_number": f"0000-26-{n:06d}",
        "report_date": "2025-12-31" if form in {"10-K", "40-F"} else date,
        "document_url": f"https://www.sec.gov/Archives/edgar/data/1/{n:018d}/doc{n}.htm",
    }


def test_select_filings_keeps_the_annual_report_behind_many_8k():
    filings = [_filing("8-K", f"2026-10-{30 - i:02d}", i) for i in range(10)]
    filings += [_filing("10-Q", "2026-07-28", 20), _filing("10-K", "2026-02-27", 21)]
    chosen = select_filings(filings)
    forms = [f["form"] for f in chosen]
    assert len(chosen) == 8
    assert "10-K" in forms and "10-Q" in forms
    # Antes: los 8 primeros eran todos 8-K.
    assert [f["form"] for f in filings[:8]] == ["8-K"] * 8


def test_select_filings_takes_40f_and_6k_issuers():
    filings = [_filing("6-K", f"2026-09-{20 - i:02d}", i) for i in range(12)]
    filings.append(_filing("40-F", "2026-03-18", 40))
    chosen = select_filings(filings)
    assert chosen[-1]["form"] == "40-F"
    assert sum(f["form"] == "6-K" for f in chosen) == 7


@contextmanager
def _company(db, ticker: str, company_type: str):
    old = db.scalar(select(Company).where(Company.ticker == ticker))
    if old is not None:
        _cleanup(db, old.id)
    company = Company(
        ticker=ticker,
        name=f"sector {ticker}",
        exchange="TEST",
        currency="USD",
        sector="Financials",
        industry="Test",
        company_type=company_type,
        valuation_model="unassigned",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.commit()
    try:
        yield company
    finally:
        _cleanup(db, company.id)


def _cleanup(db, company_id: int) -> None:
    db.rollback()
    doc_ids = db.scalars(select(Document.id).where(Document.company_id == company_id)).all()
    db.execute(delete(FinancialFact).where(FinancialFact.company_id == company_id))
    db.execute(
        delete(InferredInput).where(InferredInput.company_id == company_id),
        execution_options={"include_all_tenants": True},
    )
    if doc_ids:
        db.execute(delete(DocumentChunk).where(DocumentChunk.document_id.in_(doc_ids)))
        db.execute(delete(Document).where(Document.id.in_(doc_ids)))
    db.execute(delete(Company).where(Company.id == company_id))
    db.commit()


def _annual_doc(
    db, company, text: str, *, url: str, form: str = "10-K", filed: str = "2026-02-27"
) -> Document:
    doc = Document(
        company_id=company.id,
        title=f"{form} presentado ante la SEC",
        source_type="SEC",
        source_url=url,
        published_at=datetime.fromisoformat(filed).replace(tzinfo=UTC),
        checksum=url[-12:],
        metadata_={"form": form, "report_date": "2025-12-31", "accession_number": "0000896159-26-000005"},
    )
    db.add(doc)
    db.flush()
    db.add(DocumentChunk(document_id=doc.id, chunk_index=0, text=text, token_count=len(text.split())))
    db.commit()
    return doc


def _fact(
    db, company, metric, value, year=2025, *, unit="USD", source_type="SEC", reported=True, period=None
):
    db.add(
        FinancialFact(
            company_id=company.id,
            metric=metric,
            value=Decimal(str(value)),
            unit=unit,
            period=period or f"FY{year}",
            fiscal_year=year,
            fiscal_quarter="FY",
            source_type=source_type,
            is_reported=reported,
            confidence=Decimal("0.90"),
        )
    )


def test_ingest_filings_asks_for_the_annual_report_text_once(monkeypatch):
    init_db()
    db = SessionLocal()
    queued: list[str] = []
    filings = [_filing("8-K", f"2026-10-{28 - i:02d}", 500 + i) for i in range(9)]
    filings += [_filing("10-Q", "2026-07-28", 520), _filing("10-K", "2026-02-27", 521)]
    monkeypatch.setattr(ThesisEvidenceService, "_fetch_filings", lambda self, cik: list(filings))
    monkeypatch.setattr(
        ThesisEvidenceService,
        "_enqueue_annual_report_text",
        lambda self, db, company, filing: queued.append(filing["form"]),
    )
    try:
        with _company(db, "SECTAR1", "insurer") as company:
            result = ThesisEvidenceService()._ingest_filings(db, company, "0000000001")
            db.commit()
            assert result["annual_report"]["status"] == "queued"
            assert result["annual_report"]["form"] == "10-K"
            assert queued == ["10-K"]
            assert {i["form"] for i in result["items"]} >= {"10-K", "10-Q"}
            # Con el texto ya ingerido no se vuelve a pedir.
            doc = db.scalar(select(Document).where(Document.source_url == filings[-1]["document_url"]))
            assert doc is not None
            db.add(DocumentChunk(document_id=doc.id, chunk_index=0, text="texto del 10-K", token_count=3))
            db.commit()
            again = ThesisEvidenceService()._ingest_filings(db, company, "0000000001")
            assert again["annual_report"]["text"] == "ingested"
            assert queued == ["10-K"]
    finally:
        db.close()


def test_metadata_stub_does_not_block_the_filing_text(monkeypatch):
    from app.services.document_ingestion_service import DocumentIngestionService

    init_db()
    db = SessionLocal()
    url = "https://www.sec.gov/Archives/edgar/data/896159/000089615926000005/cb-20251231.htm"
    try:
        with _company(db, "SECSTUB", "insurer") as company:
            stub = Document(
                company_id=company.id,
                title="10-K presentado ante la SEC",
                source_type="SEC",
                source_url=url,
                metadata_={"form": "10-K", "provider": "SEC EDGAR submissions"},
            )
            db.add(stub)
            db.commit()
            html = ("<html><body><p>Annual report text. " + CB_TABLE + "</p></body></html>").encode()
            result = DocumentIngestionService().ingest_bytes(
                db,
                ticker="SECSTUB",
                title="10-K",
                content=html,
                filename="cb-20251231.htm",
                source_type="SEC",
                source_url=url,
                content_type="text/html",
                filing_metadata={"form": "10-K", "report_date": "2025-12-31"},
            )
            assert result["status"] != "duplicate"
            assert result["document_id"] == stub.id
            chunks = db.scalars(select(DocumentChunk).where(DocumentChunk.document_id == stub.id)).all()
            assert chunks
            # Una segunda ingesta del mismo archivo SI es duplicado.
            again = DocumentIngestionService().ingest_bytes(
                db,
                ticker="SECSTUB",
                title="10-K",
                content=html,
                filename="cb-20251231.htm",
                source_type="SEC",
                source_url=url,
                content_type="text/html",
            )
            assert again["status"] == "duplicate"
    finally:
        db.close()


def test_combined_ratio_and_noi_are_extracted_with_scale_and_quote():
    cr = sector_inputs.extract_combined_ratio(CB_TABLE)
    assert cr is not None and abs(cr["value"] - 0.857) < 1e-9
    assert "85.7" in cr["quote"]
    noi = sector_inputs.extract_noi(CPT_TABLE)
    assert noi is not None and noi["value"] == 1_006_834_000
    assert sector_inputs.extract_noi(CPT_TABLE.replace("(in thousands)", "")) is None
    # Solo filas de segmento que no coinciden: no hay cifra de la compañia.
    assert (
        sector_inputs.extract_combined_ratio(
            "North America combined ratio 83.0 % Overseas General combined ratio 85.2 %"
        )
        is None
    )


def test_insurer_values_with_extracted_combined_ratio_and_capm_labeled():
    init_db()
    db = SessionLocal()
    db.info["tenant_id"] = db.info.get("tenant_id")
    try:
        with _company(db, "SECINS1", "insurer") as company:
            for metric, value in (
                ("total_equity", 70_000),
                ("shares_diluted", 400),
                ("roe", 0.13),
                ("book_value_growth", 0.04),
            ):
                _fact(db, company, metric, value, unit="decimal" if value < 1 else "USD")
            _fact(db, company, "risk_free_rate", 4.2, None, unit="%", source_type="FRED", period="2026-10-18")
            _fact(db, company, "beta", 0.55, None, unit="ratio", source_type="yfinance", period="2026-10-19")
            _fact(
                db,
                company,
                "equity_risk_premium",
                0.05,
                None,
                unit="decimal",
                source_type="wacc_policy",
                period="2026-10-19",
            )
            _fact(
                db,
                company,
                "country_risk_premium",
                0.0,
                None,
                unit="decimal",
                source_type="wacc_policy",
                period="2026-10-19",
            )
            db.commit()
            before = ValuationService().value_company(db, company)
            assert before["status"] == "insufficient_data"
            assert "combined_ratio" in before["missing_inputs"]
            assert "cost_of_equity" not in before["missing_inputs"]

            doc = _annual_doc(db, company, CB_TABLE, url="https://www.sec.gov/Archives/edgar/data/9/1/cb.htm")
            out = sector_inputs.extract_from_document(db, doc)
            db.commit()
            assert out["extracted"]["combined_ratio"] == 0.857
            fact = db.scalar(
                select(FinancialFact).where(
                    FinancialFact.company_id == company.id, FinancialFact.metric == "combined_ratio"
                )
            )
            assert fact.is_reported is False and fact.source_type == "document_extract"
            assert fact.fiscal_year == 2025

            result = ValuationService().value_company(db, company)
            assert result["status"] == "ok", result.get("missing_inputs")
            items = {i["metric"]: i for i in result["estimated_inputs"]}
            assert items["cost_of_equity"]["status"] == "estimado"
            assert "CAPM" in items["cost_of_equity"]["method"]
            assert abs(items["cost_of_equity"]["value"] - (0.042 + 0.55 * 0.05)) < 1e-9
            assert items["combined_ratio"]["status"] == "inferido"
            assert "extraído del 10-K" in items["combined_ratio"]["method"]
            assert "85.7" in items["combined_ratio"]["sources"][0]["quote"]
            assert items["combined_ratio"]["note"] == sector_inputs.SINGLE_SOURCE_NOTE
            assert result["trace"]["estimated_inputs"] == result["estimated_inputs"]
            # Lo reportado no se etiqueta como estimado.
            assert "roe" not in items and "book_value" not in items
    finally:
        db.close()


def test_insurer_without_beta_keeps_cost_of_equity_missing():
    init_db()
    db = SessionLocal()
    try:
        with _company(db, "SECINS2", "insurer") as company:
            for metric, value in (
                ("total_equity", 70_000),
                ("shares_diluted", 400),
                ("roe", 0.13),
                ("book_value_growth", 0.04),
                ("combined_ratio", 0.9),
            ):
                _fact(db, company, metric, value, unit="decimal" if value < 1 else "USD")
            _fact(db, company, "risk_free_rate", 4.2, None, unit="%", source_type="FRED", period="2026-10-18")
            db.commit()
            result = ValuationService().value_company(db, company)
            assert result["status"] == "insufficient_data"
            assert "cost_of_equity" in result["missing_inputs"]
    finally:
        db.close()


def test_reit_noi_extracted_and_a_second_filing_disagreeing_is_flagged():
    init_db()
    db = SessionLocal()
    try:
        with _company(db, "SECREIT1", "reit") as company:
            _fact(db, company, "revenue", 1_580_000_000)
            db.commit()
            first = _annual_doc(
                db,
                company,
                CPT_TABLE,
                url="https://www.sec.gov/Archives/edgar/data/9/2/a.htm",
                filed="2026-02-12",
            )
            assert (
                sector_inputs.extract_from_document(db, first)["extracted"]["net_operating_income"]
                == 1_006_834_000
            )
            db.commit()
            amended = _annual_doc(
                db,
                company,
                CPT_TABLE.replace("1,006,834", "1,100,000"),
                url="https://www.sec.gov/Archives/edgar/data/9/3/b.htm",
                form="10-K/A",
                filed="2026-03-01",
            )
            sector_inputs.extract_from_document(db, amended)
            db.commit()
            db.refresh(amended)
            note = amended.metadata_["sector_extracts"]["net_operating_income"]["note"]
            assert note.startswith("discrepancia")
            # Escala mal leida (NOI > ingresos): no se escribe nada.
            bad = _annual_doc(
                db,
                company,
                CPT_TABLE.replace("in thousands", "in millions"),
                url="https://www.sec.gov/Archives/edgar/data/9/4/c.htm",
                filed="2026-02-13",
            )
            assert sector_inputs.extract_from_document(db, bad)["extracted"]["net_operating_income"] is None
    finally:
        db.close()
