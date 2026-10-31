"""Generate auto-ingiere evidencia best-effort (hermetico: mocks, sin red).

  1. Con mocks de EDGAR (companyfacts+filings), Finnhub (quote+profile),
     calendario NASDAQ e IR: generate ASTS persiste FinancialFacts y
     MarketPrice y la tesis sale parcial-publicable (seccion 13 con rango
     indicativo + reverse DCF) en vez de NO VALUATION.
  2. Sin red (todos los fetches lanzan): generate degrada al esqueleto
     honesto insufficient_data con HTTP 200, nunca 500.
  3. Audit limpio (coverage 100, sin unsupported) bloqueado aguas abajo:
     el red-team dice "blocked", nunca "failed with coverage 100".

Run from data-engine/:
    pytest tests/test_thesis_auto_ingest.py -v
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

import main
from app.core.database import SessionLocal, init_db
from app.models import (
    Company,
    Document,
    FinancialFact,
    MarketPrice,
    NewsEvent,
    SourceAudit,
    ThesisVersion,
    Transcript,
)
from app.seed import seed
from app.services.connectors.base import ConnectorItem, ConnectorResult
from app.services.red_team_service import RedTeamService
from app.services.thesis_evidence_service import ThesisEvidenceService
from tests.auth_helpers import csrf_client


def _xbrl(val, end, filed, form="10-K", fy=None):
    return {
        "val": val,
        "end": end,
        "filed": filed,
        "form": form,
        "fy": fy if fy is not None else int(end[:4]),
        "fp": "FY",
    }


FAKE_COMPANYFACTS = {
    "entityName": "AST SpaceMobile, Inc.",
    "facts": {
        "us-gaap": {
            "RevenueFromContractWithCustomerExcludingAssessedTax": {
                "units": {
                    "USD": [
                        _xbrl(5_000_000, "2023-12-31", "2024-03-28"),
                        _xbrl(48_400_000, "2024-12-31", "2025-02-28"),
                    ]
                }
            },
            "WeightedAverageNumberOfDilutedSharesOutstanding": {
                "units": {"shares": [_xbrl(300_000_000, "2024-12-31", "2025-02-28")]}
            },
            "Assets": {
                "units": {
                    "USD": [
                        _xbrl(900_000_000, "2023-12-31", "2024-03-28"),
                        _xbrl(1_500_000_000, "2024-12-31", "2025-02-28"),
                    ]
                }
            },
            "NetIncomeLoss": {
                "units": {"USD": [_xbrl(-300_000_000, "2024-12-31", "2025-02-28")]}
            },
            "NetCashProvidedByUsedInOperatingActivities": {
                "units": {"USD": [_xbrl(-200_000_000, "2024-12-31", "2025-02-28")]}
            },
            "CashAndCashEquivalentsAtCarryingValue": {
                "units": {"USD": [_xbrl(500_000_000, "2024-12-31", "2025-02-28")]}
            },
        }
    },
}

FAKE_FILINGS = [
    {
        "form": "10-K",
        "accession_number": "0001780312-25-000001",
        "filing_date": "2025-02-28",
        "report_date": "2024-12-31",
        "primary_document": "asts-20241231.htm",
        "index_url": "https://www.sec.gov/Archives/edgar/data/1780312/000178031225000001/",
        "document_url": "https://www.sec.gov/Archives/edgar/data/1780312/000178031225000001/asts-20241231.htm",
    },
    {
        "form": "8-K",
        "accession_number": "0001780312-25-000002",
        "filing_date": "2025-03-10",
        "report_date": "2025-03-10",
        "primary_document": "asts-8k.htm",
        "index_url": "https://www.sec.gov/Archives/edgar/data/1780312/000178031225000002/",
        "document_url": "https://www.sec.gov/Archives/edgar/data/1780312/000178031225000002/asts-8k.htm",
    },
]

FAKE_QUOTE = {"c": 25.50, "h": 26.0, "l": 24.8, "o": 25.0, "pc": 24.0, "t": 1_700_000_000}
FAKE_PROFILE = {
    "name": "AST SpaceMobile Inc",
    "exchange": "NASDAQ",
    "marketCapitalization": 8000.0,  # millones USD
    "currency": "USD",
}


def _mock_all_sources(monkeypatch, *, earnings_date: str | None = None):
    next_date = earnings_date or (date.today() + timedelta(days=7)).isoformat()
    monkeypatch.setattr(
        ThesisEvidenceService, "_fetch_company_facts", lambda self, cik: FAKE_COMPANYFACTS
    )
    monkeypatch.setattr(
        ThesisEvidenceService, "_fetch_filings", lambda self, cik: list(FAKE_FILINGS)
    )
    monkeypatch.setattr(
        ThesisEvidenceService, "_fetch_quote", lambda self, ticker: dict(FAKE_QUOTE)
    )
    monkeypatch.setattr(
        ThesisEvidenceService, "_fetch_profile", lambda self, ticker: dict(FAKE_PROFILE)
    )
    monkeypatch.setattr(
        ThesisEvidenceService,
        "_fetch_earnings",
        lambda self: {
            "status": "ok",
            "events": [
                {
                    "symbol": "ASTS",
                    "date": next_date,
                    "time": "bmo",
                    "eps_forecast": -0.20,
                }
            ],
            "errors": [],
        },
    )
    monkeypatch.setattr(
        ThesisEvidenceService,
        "_fetch_ir",
        lambda self, ir_url, ticker: ConnectorResult(
            source="ir",
            items=[
                ConnectorItem(
                    source="ir",
                    title="Investor Day 2025 Presentation",
                    url="https://investors.ast-science.com/investor-day-2025",
                    ticker=ticker,
                    item_type="filing",
                )
            ],
        ),
    )


def _mock_no_network(monkeypatch):
    def _boom(self, *args, **kwargs):
        raise RuntimeError("sin red: conexion rechazada")

    for name in (
        "_fetch_cik",
        "_fetch_company_facts",
        "_fetch_filings",
        "_fetch_quote",
        "_fetch_profile",
        "_fetch_earnings",
        "_fetch_ir",
    ):
        monkeypatch.setattr(ThesisEvidenceService, name, _boom)


def _clean_asts_evidence():
    """Aislamiento: la DB de test es compartida; borra evidencia ASTS previa."""
    # El fixture autouse corre antes que el test: en una DB recién creada
    # (fichero suelto o primer test del proceso) aún no hay tablas.
    init_db()
    db = SessionLocal()
    try:
        company = db.scalar(select(Company).where(Company.ticker == "ASTS"))
        if company is None:
            return
        for fact in db.scalars(
            select(FinancialFact).where(FinancialFact.company_id == company.id)
        ).all():
            db.delete(fact)
        for price in db.scalars(
            select(MarketPrice).where(MarketPrice.company_id == company.id)
        ).all():
            db.delete(price)
        for news in db.scalars(
            select(NewsEvent).where(NewsEvent.company_id == company.id)
        ).all():
            db.delete(news)
        for tr in db.scalars(
            select(Transcript).where(Transcript.company_id == company.id)
        ).all():
            db.delete(tr)
        for doc in db.scalars(
            select(Document).where(Document.company_id == company.id)
        ).all():
            db.delete(doc)
        db.commit()
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _isolated_asts_evidence():
    _clean_asts_evidence()
    yield
    _clean_asts_evidence()


def _seed_evidence_rows():
    """News material + transcript + tesis externa pegada (lectura, sin red)."""
    db = SessionLocal()
    try:
        company = db.scalar(select(Company).where(Company.ticker == "ASTS"))
        assert company is not None
        db.add(
            NewsEvent(
                company_id=company.id,
                date=datetime.now(UTC),
                title="ASTS firma acuerdo comercial con operadora",
                source="press",
                url="https://example.com/asts-mno",
                summary="Acuerdo comercial material con operadora.",
                event_type="partnership",
                materiality_score=8,
                impact_direction="positive",
            )
        )
        doc = Document(
            company_id=company.id,
            title="Q4 2024 earnings call transcript",
            source_type="manual_transcript",
            source_url=None,
        )
        db.add(doc)
        db.flush()
        db.add(
            Transcript(
                company_id=company.id,
                title="Q4 2024 earnings call transcript",
                period="2024-Q4",
                source_id=doc.id,
                transcript_text="operador: despliegue...",
            )
        )
        db.add(
            Document(
                company_id=company.id,
                title="Tesis externa: ASTS deep dive",
                source_type="external_thesis",
                source_url="https://example.com/asts-deep-dive",
            )
        )
        db.commit()
    finally:
        db.close()


def test_generate_with_mocked_sources_persists_facts_and_blocks_range_on_cash_burn(monkeypatch):
    """OCF reportado -200M: el margen FCF base positivo supuesto lo contradice.

    Ya no hay rango indicativo por accion (bear/base/bull/margen de seguridad
    None): insufficient_data con causa e inputs pendientes. Las fuentes y los
    hechos reales se siguen persistiendo y mostrando. El camino con caja
    positiva (sigue indicativo) esta en test_thesis_indicative_positive_cash.py.
    """
    init_db()
    seed()
    _clean_asts_evidence()
    _mock_all_sources(monkeypatch)
    _seed_evidence_rows()
    client = csrf_client(main.app)

    response = client.post("/api/thesis/generate", json={"ticker": "ASTS", "force_new_version": True})
    assert response.status_code == 200
    thesis = response.json()
    assert thesis["status"] == "insufficient_data"
    assert thesis["bear_value"] is None
    assert thesis["base_value"] is None
    assert thesis["bull_value"] is None
    assert thesis["expected_value"] is None
    assert thesis["current_price"] is not None and float(thesis["current_price"]) == 25.50
    assert "no publicable" in thesis["executive_summary"]
    assert "FCF normalizado o margen FCF" in thesis["executive_summary"]

    markdown = thesis["thesis_markdown"]
    assert "SIN VALORACIÓN — datos insuficientes" in markdown
    assert "RANGO INDICATIVO PARCIAL" not in markdown
    # Fuentes: conseguido con detalle, sin datos inventados.
    assert "Fundamentales: conseguido" in markdown
    assert "revenue" in markdown and "shares_diluted" in markdown
    assert "Próximos resultados:" in markdown
    assert "Última transcripción: Q4 2024 earnings call transcript" in markdown
    assert "ASTS firma acuerdo comercial" in markdown
    assert "Investor Day 2025 Presentation" in markdown
    assert "Tesis externas: conseguido" in markdown or "tesis pegadas" in markdown

    db = SessionLocal()
    try:
        company = db.scalar(select(Company).where(Company.ticker == "ASTS"))
        fact_metrics = {
            f.metric
            for f in db.scalars(
                select(FinancialFact).where(FinancialFact.company_id == company.id)
            ).all()
        }
        assert {"revenue", "shares_diluted", "total_assets"} <= fact_metrics
        revenue = db.scalar(
            select(FinancialFact).where(
                FinancialFact.company_id == company.id, FinancialFact.metric == "revenue"
            )
        )
        assert revenue.source_type == "SEC" and revenue.source_id is not None
        price = db.scalar(
            select(MarketPrice)
            .where(MarketPrice.company_id == company.id)
            .order_by(MarketPrice.date.desc())
            .limit(1)
        )
        assert price is not None and float(price.close) == 25.50 and price.source == "Finnhub"
        # Sin missing criticos financieros (revenue/shares resueltos).
        missing = " ".join(thesis["executive_summary"].split())
        assert "FCF normalizado o margen FCF" in missing
    finally:
        db.close()


def test_generate_without_network_degrades_to_honest_skeleton(monkeypatch):
    init_db()
    seed()
    _clean_asts_evidence()
    _mock_no_network(monkeypatch)
    client = csrf_client(main.app)

    response = client.post("/api/thesis/generate", json={"ticker": "ASTS", "force_new_version": True})
    assert response.status_code == 200
    thesis = response.json()
    assert thesis["status"] == "insufficient_data"
    assert thesis["bear_value"] is None
    assert thesis["expected_value"] is None
    assert "no publicable" in thesis["executive_summary"]
    markdown = thesis["thesis_markdown"]
    assert "SIN VALORACIÓN — datos insuficientes" in markdown
    assert "Pendiente:" in markdown
    assert "Pendiente transcripción" in markdown


def test_clean_audit_blocked_downstream_is_not_failed():
    init_db()
    seed()
    db = SessionLocal()
    try:
        company = db.scalar(select(Company).where(Company.ticker == "ASTS"))
        assert company is not None
        thesis = ThesisVersion(
            company_id=company.id,
            version=1,
            status="insufficient_data",
            thesis_markdown="# ASTS Thesis v1",
            executive_summary="blocked",
            rating="insufficient_data",
        )
        db.add(thesis)
        db.flush()
        db.add(
            SourceAudit(
                thesis_version_id=thesis.id,
                passed=False,
                source_coverage_score=100,
                unsupported_claims=[],
                weak_claims=[],
                data_conflicts=[],
                required_fixes=["Missing valuation inputs: revenue"],
            )
        )
        db.commit()

        run = RedTeamService().run(db, company, thesis, commit=False)
        messages = [f["message"] for f in run.findings]
        # F301: el mensaje visible va en español y habla de puntuación de
        # respaldo de afirmaciones, nunca de «cobertura» global.
        assert not any("Source audit failed with coverage 100" in m for m in messages)
        blocked = [f for f in run.findings if f["type"] == "source_audit_blocked"]
        assert blocked, messages
        assert "sin afirmaciones sin respaldo" in blocked[0]["message"]
        assert "puntuación de respaldo de afirmaciones" in blocked[0]["message"]
        assert "cobertura" not in blocked[0]["message"]
    finally:
        db.close()
