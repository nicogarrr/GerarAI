import asyncio
import json
from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.api.routes.sources import source_audits
from app.core.database import Base
from app.llm.base import LLMProvider
from app.llm.contracts import LLMRequest, LLMResponse, Message, Usage
from app.llm.routing import TaskModelRouter
from app.models import (
    Company,
    CompanyKPI,
    Document,
    DocumentChunk,
    FactRevision,
    FinancialFact,
    KPIExtractionCandidate,
    MarketPrice,
    ResearchAlert,
    SourceAudit,
    ThesisVersion,
)
from app.schemas import ChatResponse
from app.services.alert_rule_service import AlertRuleService
from app.services.chat_synthesis_service import ChatSynthesisService
from app.services.kpi_extraction_service import KPIExtractionService
from app.services.metric_semantics import MetricSemanticsRegistry


class StaticProvider(LLMProvider):
    name = "test-provider"

    def __init__(self, payload):
        super().__init__(
            model_router=TaskModelRouter(default_model="test-model"),
            timeout_seconds=1,
            max_retries=0,
        )
        self.payload = payload

    async def complete(self, request: LLMRequest) -> LLMResponse:
        payload = self.payload(request) if callable(self.payload) else self.payload
        return LLMResponse(
            message=Message("assistant", json.dumps(payload)),
            usage=Usage(100, 50, 150, cache_read_tokens=20),
            model="test-model",
            provider=self.name,
            request_id="test-request",
        )


def _company(ticker: str, company_type: str = "standard", tags=None) -> Company:
    return Company(
        ticker=ticker,
        name=f"{ticker} Test",
        exchange="TEST",
        currency="USD",
        sector="Test",
        industry="Test",
        company_type=company_type,
        valuation_model="standard_dcf",
        special_sources=[],
        special_risks=[],
        factor_tags=tags or [],
    )


def test_source_audits_are_company_specific_and_paginated():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        first = _company("AUD1")
        second = _company("AUD2")
        db.add_all([first, second])
        db.flush()
        first_thesis = ThesisVersion(
            company_id=first.id,
            version=1,
            thesis_markdown="# First",
            executive_summary="First thesis",
        )
        second_thesis = ThesisVersion(
            company_id=second.id,
            version=1,
            thesis_markdown="# Second",
            executive_summary="Second thesis",
        )
        db.add_all([first_thesis, second_thesis])
        db.flush()
        first_audit = SourceAudit(thesis_version_id=first_thesis.id, passed=True)
        second_audit = SourceAudit(thesis_version_id=second_thesis.id, passed=False)
        db.add_all([first_audit, second_audit])
        db.flush()

        rows = source_audits(ticker="aud1", limit=1, offset=0, db=db)

        assert [row["id"] for row in rows] == [first_audit.id]


def test_kpi_extraction_requires_verified_locator_and_approval_before_fact():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.info["tenant_id"] = "intelligence-kpi-fixture"
        company = _company("ASTS", "space_telecom_pre_fcf", ["space", "telecom"])
        db.add(company)
        db.flush()
        document = Document(
            company_id=company.id,
            title="FY2025 update",
            source_type="company_ir",
        )
        db.add(document)
        db.flush()
        chunk = DocumentChunk(
            document_id=document.id,
            chunk_index=0,
            text="Penetration reached 12.5% in FY2025.",
        )
        db.add(chunk)
        db.commit()

        provider = StaticProvider(
            {
                "observations": [
                    {
                        "metric_key": "penetration",
                        "raw_label": "Penetration",
                        "raw_value": "12.5%",
                        "raw_unit": "percent",
                        "period": "FY2025",
                        "fiscal_year": 2025,
                        "fiscal_quarter": "FY",
                        "chunk_id": chunk.id,
                        "quote": "Penetration reached 12.5% in FY2025.",
                        "confidence": 0.95,
                    }
                ]
            }
        )
        candidates = asyncio.run(
            KPIExtractionService(provider).extract_document(db, document)
        )
        assert len(candidates) == 1
        candidate = candidates[0]
        assert candidate.normalized_value == Decimal("0.125")
        assert candidate.status == "pending_approval"
        assert db.scalar(select(FinancialFact)) is None

        fact = KPIExtractionService(provider).approve(db, candidate, actor="analyst")
        assert fact.metric == "penetration"
        assert fact.value == Decimal("0.125")
        assert fact.source_id == document.id
        assert candidate.canonical_fact_id == fact.id


def test_kpi_approval_versions_a_contradicting_canonical_fact():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        company = _company("REV")
        db.add(company)
        db.flush()
        first_document = Document(
            company_id=company.id,
            title="Original filing",
            source_type="sec_filing",
        )
        second_document = Document(
            company_id=company.id,
            title="Restated filing",
            source_type="company_ir",
        )
        db.add_all([first_document, second_document])
        db.flush()
        chunk = DocumentChunk(
            document_id=second_document.id,
            chunk_index=0,
            text="Penetration was restated to 12.5% for FY2025.",
        )
        db.add(chunk)
        db.flush()
        fact = FinancialFact(
            company_id=company.id,
            metric="penetration",
            value=Decimal("0.10"),
            unit="decimal",
            period="FY2025",
            fiscal_year=2025,
            fiscal_quarter="FY",
            source_id=first_document.id,
            source_type=first_document.source_type,
            confidence=Decimal("0.80"),
        )
        db.add(fact)
        db.flush()
        kpi = CompanyKPI(
            company_id=company.id,
            metric_key="penetration",
            display_name="Penetration",
            canonical_unit="decimal",
        )
        db.add(kpi)
        db.flush()
        candidate = KPIExtractionCandidate(
            company_id=company.id,
            company_kpi_id=kpi.id,
            document_id=second_document.id,
            document_chunk_id=chunk.id,
            metric_key="penetration",
            raw_label="Penetration",
            raw_value="12.5%",
            raw_unit="percent",
            normalized_value=Decimal("0.125"),
            canonical_unit="decimal",
            period="FY2025",
            fiscal_year=2025,
            fiscal_quarter="FY",
            source_locator={"chunk_id": chunk.id, "quote": chunk.text},
            reconciliation_status="reconciled",
            status="pending_approval",
            confidence=Decimal("0.95"),
        )
        db.add(candidate)
        db.commit()
        canonical_id = fact.id

        approved = KPIExtractionService(StaticProvider({})).approve(
            db, candidate, actor="analyst"
        )

        revision = db.scalar(select(FactRevision))
        assert approved.id == canonical_id
        assert approved.value == Decimal("0.125")
        assert approved.source_id == second_document.id
        assert db.query(FinancialFact).count() == 1
        assert revision is not None
        assert revision.previous_value == Decimal("0.10")
        assert revision.new_value == Decimal("0.125")
        assert revision.canonical_version == 1
        assert revision.approved_by == "analyst"
        assert revision.status == "approved"
        assert revision.source["candidate_id"] == candidate.id


def test_alert_rule_is_evaluated_and_respects_cooldown():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        company = _company("RULE")
        db.add(company)
        db.flush()
        db.add(
            MarketPrice(
                company_id=company.id,
                date=date.today(),
                close=Decimal("120"),
                source="test",
            )
        )
        db.commit()
        service = AlertRuleService()
        rule = service.create(
            db,
            company,
            rule_type="price_above",
            operator=">",
            value=100,
            cooldown_seconds=3600,
        )
        first = service.evaluate(db, rule)
        second = service.evaluate(db, rule)
        assert first["status"] == "triggered"
        assert second["cooldown_active"] is True
        assert rule.trigger_count == 1
        assert rule.last_evaluated_at is not None
        assert rule.last_triggered_at is not None
        assert db.scalar(select(ResearchAlert)) is not None


def test_metric_semantics_distinguish_lower_is_better_and_context_metrics():
    assert MetricSemanticsRegistry.get("net_debt").direction == "lower_is_better"
    assert MetricSemanticsRegistry.get("shares_diluted").tolerance == Decimal("0.02")
    assert MetricSemanticsRegistry.get("capital_expenditure").direction == "context_dependent"


def _chat_payload(citation: str) -> dict:
    keys = (
        "facts", "calculations", "user_hypotheses", "unverified_claims", "inferences",
        "contradictions", "insufficient_data", "conclusion",
    )
    return {
        "sections": [
            {
                "key": key,
                "body": f"Grounded {key}",
                "citations": [citation] if key in {"facts", "calculations", "inferences", "conclusion"} else [],
            }
            for key in keys
        ],
        "confidence": 0.8,
        "insufficient_data": False,
        "answer": "Respuesta natural en prosa con la cifra citada en su seccion.",
    }


def test_chat_llm_synthesis_verifies_citations_and_falls_back_on_hallucination():
    baseline = ChatResponse(
        answer="deterministic",
        sections=[
            {"key": key, "body": key, "citations": ["financial_fact:1"] if key in {"facts", "calculations", "inferences", "conclusion"} else []}
            for key in (
                "facts", "calculations", "user_hypotheses", "unverified_claims", "inferences",
                "contradictions", "insufficient_data", "conclusion",
            )
        ],
        sources=[{"type": "financial_fact", "id": 1, "title": "Revenue FY2025"}],
        model="deterministic",
    )
    valid = asyncio.run(
        ChatSynthesisService(StaticProvider(_chat_payload("financial_fact:1"))).synthesize(
            question="What changed?", ticker="TEST", baseline=baseline
        )
    )
    assert valid.model == "test-model"
    assert valid.llm_trace["citation_verification"] is True
    assert valid.llm_trace["cache_read_tokens"] == 20
    assert valid.answer == "Respuesta natural en prosa con la cifra citada en su seccion."
    assert "HECHO" not in valid.answer
    assert any(section.key == "facts" for section in valid.sections)

    invalid_baseline = baseline.model_copy(deep=True)
    invalid_baseline.answer = "safe deterministic answer"
    invalid = asyncio.run(
        ChatSynthesisService(StaticProvider(_chat_payload("financial_fact:999"))).synthesize(
            question="What changed?", ticker="TEST", baseline=invalid_baseline
        )
    )
    assert invalid.model == "test-model" or invalid.model == "deterministic"
    assert invalid.llm_trace["fallback"] is True
    assert invalid.answer == "safe deterministic answer"
