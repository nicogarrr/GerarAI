import asyncio
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, CompanyKPI, Document, DocumentChunk, FinancialFact
from app.services import kpi_deterministic as parser
from app.services import kpi_extraction_service as service


def row(key="revenue", unit="USD", aliases=None):
    return SimpleNamespace(metric_key=key, canonical_unit=unit, active=True,
                           aliases=aliases if aliases is not None else [key], required=True)


def chunk(text, id=1):
    return SimpleNamespace(id=id, text=text)


def test_strict_rows_preserve_quote_and_unit_period():
    text = "Revenue | FY2025 | USD million | (123.4)"
    out = parser.extract([chunk(text)], [row(aliases=["Revenue"])], source_type="IR")
    assert len(out) == 1
    assert out[0]["quote"] == text
    assert out[0]["raw_value"] == "(123.4)"
    assert out[0]["raw_unit"] == "USD million"
    assert out[0]["period"] == "FY2025"
    assert out[0]["_deterministic"]["parser"] == "explicit-row"


@pytest.mark.parametrize("text", [
    "Revenue | 2025 | USD million | 10",  # no explicit fiscal period
    "Revenue | FY2025 | $ million | 10",  # ambiguous currency
    "Revenue | FY2025 | CAD million | 10",  # unsupported currency
    "Revenue | FY2025 | EUR million | 10",  # wrong currency
    "Revenue | FY2025 | USD million | NaN",
    "Revenue | FY2025 | USD million | 10 | 20",  # multi-column ambiguity
    "Projected Revenue | FY2025 | USD million | 10",  # not exact label
])
def test_ambiguous_or_forecast_rows_not_guessed(text):
    assert parser.extract([chunk(text)], [row()], source_type="SEC") == []


def test_unknown_alias_collision_and_source_rejected():
    text = "Revenue | FY2025 | USD | 100"
    assert parser.extract([chunk(text)], [row()], source_type="blog") == []
    assert parser.extract([chunk(text)], [row(aliases=["Revenue"]), row("other", aliases=["Revenue"])], source_type="IR") == []
    assert parser.extract([chunk("Seats | Q12025 | count | 12")], [row("seats", "count")], source_type="SEC")[0]["raw_value"] == "12"
    assert parser.extract([chunk("Margin | Q12025 | percent | 12.5")], [row("margin", "decimal")], source_type="IR")[0]["raw_unit"] == "percent"
    assert parser.extract([chunk("Margin | Q12025 | count | 12")], [row("margin", "decimal")], source_type="IR") == []


XML = '''<html xmlns:ix="http://www.xbrl.org/2013/inlineXBRL" xmlns:x="http://www.xbrl.org/2003/instance" xmlns:us-gaap="http://fasb.org/us-gaap/2025" xmlns:dei="http://xbrl.sec.gov/dei/2025" xmlns:iso4217="http://www.xbrl.org/2003/iso4217">
<x:context id="fy"><x:entity><x:identifier>000123</x:identifier></x:entity><x:period><x:startDate>2024-01-01</x:startDate><x:endDate>2024-12-31</x:endDate></x:period></x:context>
<x:unit id="usd"><x:measure>iso4217:USD</x:measure></x:unit>
<ix:nonNumeric name="dei:DocumentFiscalYearFocus" contextRef="fy">2024</ix:nonNumeric>
<ix:nonFraction name="us-gaap:Revenues" contextRef="fy" unitRef="usd" scale="6">123.4</ix:nonFraction></html>'''


def test_xbrl_requires_exact_entity_context_currency_and_fiscal_year():
    out = parser.extract([chunk(XML)], [row()], source_type="SEC", cik="123")
    assert len(out) == 1
    assert out[0]["quote"] == XML
    assert out[0]["raw_unit"] == "USD million"
    assert out[0]["period"] == "FY2024"
    assert out[0]["_deterministic"]["context_id"] == "fy"
    assert parser.extract([chunk(XML)], [row()], source_type="IR", cik="123") == []
    assert parser.extract([chunk(XML)], [row()], source_type="SEC") == []


@pytest.mark.parametrize("before,after", [
    ("http://fasb.org/us-gaap/2025", "https://evil.invalid/gaap"),
    ("http://xbrl.sec.gov/dei/2025", "http://invalid/dei"),
    ("000123", "000456"),
    ("<x:entity>", "<x:entity><x:segment/>"),
    ("2024-01-01", "2024-10-01"),
    ("2024-01-01", "bad-date"),
    ('scale="6"', 'scale="10"'),
    ('scale="6"', 'scale="bad"'),
    ('scale="6"', 'scale="6" format="ixt:num-dot-decimal"'),
    ("123.4", "NaN"),
    ("iso4217:USD", "iso4217:EUR"),
    ("us-gaap:Revenues", "custom:Revenues"),
    ("dei:DocumentFiscalYearFocus", "unknown:Year"),
    ('contextRef="fy" unitRef', 'contextRef="missing" unitRef'),
    ("<x:unit", "<x:unit-bad"),
    ("</html>", ""),
])
def test_xbrl_ambiguous_fragments_rejected(before, after):
    assert parser.extract([chunk(XML.replace(before, after))], [row()], source_type="SEC", cik="123") == []


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.info["tenant_id"] = "fixture"
        company = Company(ticker="T", name="T", exchange="TEST", currency="USD", cik="123", company_type="holding", valuation_model="unassigned")
        db.add(company)
        db.flush()
        doc = Document(company_id=company.id, title="Results", source_type="IR", metadata_={})
        db.add(doc)
        db.flush()
        db.add(DocumentChunk(document_id=doc.id, chunk_index=70, text="Revenue | FY2025 | USD million | 12"))
        registry = [CompanyKPI(company_id=company.id, metric_key="revenue", display_name="Revenue", aliases=["Revenue"], canonical_unit="USD", active=True)]
        db.add_all(registry)
        db.commit()
        monkeypatch.setattr(service.CompanyKPIRegistryService, "sync", lambda *a, **k: registry)
        yield db, doc, registry
    engine.dispose()


def test_zero_euro_mode_never_builds_provider_or_calls_gate_budget_quota(db, monkeypatch):
    session, doc, _ = db
    def forbidden(*a, **k):
        raise AssertionError("paid/gated path called")
    monkeypatch.setattr(service, "create_llm_provider", forbidden)
    monkeypatch.setattr(service, "BudgetController", forbidden)
    monkeypatch.setattr("app.services.jev_gates.kpi_chunk_keep_flags", forbidden)
    monkeypatch.setattr("app.services.kpi_call_quota.reserve", forbidden)
    monkeypatch.setenv("KPI_EXTRACTION_MODE", "deterministic-only")
    out = asyncio.run(service.KPIExtractionService().extract_document(session, doc))
    assert len(out) == 1
    candidate = out[0]
    assert candidate.normalized_value == Decimal("12000000")
    assert candidate.status == "needs_review"  # table units precede figure; no grounding bypass
    assert candidate.source_locator["quote"] == "Revenue | FY2025 | USD million | 12"
    assert candidate.trace["provider"] == "deterministic"
    assert session.scalar(select(FinancialFact)) is None
    retry = asyncio.run(service.KPIExtractionService().extract_document(session, doc))
    assert [x.id for x in retry] == [candidate.id]
    assert doc.metadata_["kpi_deterministic"]["covered_metrics"] == ["revenue"]


def test_zero_euro_unresolved_stays_visible_without_llm(db, monkeypatch):
    session, doc, registry = db
    registry.append(CompanyKPI(company_id=doc.company_id, metric_key="aum", display_name="Aum", canonical_unit="USD", active=True))
    session.add(registry[-1]); session.commit()
    monkeypatch.setattr(service, "create_llm_provider", lambda: pytest.fail("provider created"))
    out = asyncio.run(service.KPIExtractionService().extract_document(session, doc, mode="deterministic-only"))
    assert len(out) == 1
    assert doc.metadata_["kpi_deterministic"]["unresolved_metrics"] == ["aum"]
    assert doc.metadata_["kpi_deterministic"]["complete"] is False


def test_auto_fallback_only_requests_unresolved_metrics(db, monkeypatch):
    from app.llm.contracts import LLMResponse, Message, Usage
    session, doc, registry = db
    registry.append(CompanyKPI(company_id=doc.company_id, metric_key="aum", display_name="Aum", canonical_unit="USD", active=True))
    session.add(registry[-1]); session.commit()
    monkeypatch.setattr("app.services.jev_gates.kpi_chunk_keep_flags", AsyncMock(return_value=None))
    monkeypatch.setattr("app.services.kpi_call_quota.reserve", lambda *a: None)
    response = LLMResponse(message=Message("assistant", '{"observations": []}'), model="test", provider="test", usage=Usage(1, 1, 2))
    provider = SimpleNamespace(complete=AsyncMock(return_value=response))
    out = asyncio.run(service.KPIExtractionService(provider).extract_document(session, doc))
    assert len(out) == 1
    import json
    request = provider.complete.call_args.args[0]
    assert [x["metric_key"] for x in json.loads(request.messages[-1].content)["registry"]] == ["aum"]


def test_conflicting_rows_are_not_approvable(db):
    session, doc, _ = db
    session.add(DocumentChunk(document_id=doc.id, chunk_index=71, text="Revenue | FY2025 | USD million | 99"))
    session.commit()
    out = asyncio.run(service.KPIExtractionService().extract_document(session, doc, mode="deterministic-only"))
    assert len(out) == 2
    assert all(x.status == "needs_review" for x in out)
    with pytest.raises(ValueError):
        service.KPIExtractionService().approve(session, out[0], actor="test")


def test_invalid_mode_and_missing_company_do_not_create_provider(db):
    session, doc, _ = db
    with pytest.raises(ValueError, match="mode"):
        asyncio.run(service.KPIExtractionService().extract_document(session, doc, mode="pay"))
    doc.company_id = None
    with pytest.raises(ValueError, match="company-specific"):
        asyncio.run(service.KPIExtractionService().extract_document(session, doc, mode="deterministic-only"))


def test_zero_euro_no_observations_reports_all_unresolved(db, monkeypatch):
    session, doc, _ = db
    session.scalar(select(DocumentChunk)).text = "Revenue grew 25% to $3 million last year"
    session.commit()
    monkeypatch.setattr(service, "create_llm_provider", lambda: pytest.fail("provider created"))
    assert asyncio.run(service.KPIExtractionService().extract_document(session, doc, mode="deterministic-only")) == []
    assert doc.metadata_["kpi_deterministic"]["unresolved_metrics"] == ["revenue"]


def test_measurement_uses_document_registry_denominator():
    from scripts.measure_kpi_deterministic import measure
    payload = {"documents": [{"source_type": "IR", "chunks": [{"id": 1, "text": "Revenue | FY2025 | USD | 12"}],
        "kpi_registry": [vars(row()), vars(row("aum"))]}]}
    out = measure(payload)
    assert out["coverage_percent"] == 50
    assert out["covered_opportunities"] == 1
    assert out["registry_opportunities"] == 2


def test_auto_with_registry_covered_never_constructs_provider(db, monkeypatch):
    session, doc, _ = db
    monkeypatch.setattr(service, "create_llm_provider", lambda: pytest.fail("provider created"))
    assert len(asyncio.run(service.KPIExtractionService().extract_document(session, doc))) == 1


def test_deterministic_candidates_survive_fallback_failure(db, monkeypatch):
    session, doc, registry = db
    registry.append(CompanyKPI(company_id=doc.company_id, metric_key="aum", display_name="Aum", canonical_unit="USD", active=True))
    session.add(registry[-1]); session.commit()
    monkeypatch.setattr("app.services.jev_gates.kpi_chunk_keep_flags", AsyncMock(return_value=None))
    monkeypatch.setattr("app.services.kpi_call_quota.reserve", lambda *a: None)
    provider = SimpleNamespace(complete=AsyncMock(side_effect=RuntimeError("LLM unavailable")))
    with pytest.raises(RuntimeError, match="LLM unavailable"):
        asyncio.run(service.KPIExtractionService(provider).extract_document(session, doc))
    session.rollback()
    from app.models import KPIExtractionCandidate
    assert session.scalar(select(KPIExtractionCandidate)) is not None
    assert session.scalar(select(FinancialFact)) is None


def test_lazy_provider_is_only_created_when_accessed(monkeypatch):
    calls = []
    provider = object()
    monkeypatch.setattr(service, "create_llm_provider", lambda: calls.append(True) or provider)
    instance = service.KPIExtractionService()
    assert calls == []
    assert instance.provider is provider
    assert instance.provider is provider
    assert calls == [True]


ANCHOR = 'The Company announced financial results for the quarter ended March 31, 2025 (“Q1 2025”).'
MARGIN = 'Gross profit in the quarter increased to $10.1 million, implying a gross margin of 62.7% compared to 44.8%. Future quarters are expected to change.'


def test_ir_result_uses_exact_current_margin_not_comparative_and_cites_period():
    chunks = [chunk(ANCHOR, 1), chunk(MARGIN, 2)]
    out = parser.extract(chunks, [row("gross_margin", "decimal")], source_type="IR")
    assert len(out) == 1
    assert out[0]["raw_value"] == "62.7"
    assert out[0]["period"] == "Q12025"
    assert "44.8%" in out[0]["quote"]
    assert "Future" not in out[0]["quote"]
    assert out[0]["_deterministic"]["context"]["chunk_id"] == 1
    assert out[0]["_deterministic"]["context"]["quote"] in ANCHOR


@pytest.mark.parametrize("text", [
    'Gross profit in the quarter is expected to change. Gross margin target was 62.7%.',
    'For the quarter, we expect gross margin of 62.7%.',
    'In the prior year gross margin was 62.7% for the quarter.',
    '{"description": "Gross margin was 62.7% in the quarter"}',
    'Gross margin was 62.7% for the year.',
])
def test_ir_future_prior_json_or_year_not_assigned_to_current_quarter(text):
    assert parser.extract([chunk(ANCHOR, 1), chunk(text, 2)], [row("gross_margin", "decimal")], source_type="IR") == []


def test_ir_mixed_quarter_context_or_distant_anchor_rejected():
    registry = [row("gross_margin", "decimal")]
    assert parser.extract([chunk(ANCHOR + ANCHOR.replace("Q1", "Q2")), chunk(MARGIN)], registry, source_type="IR") == []
    assert parser.extract([chunk(ANCHOR), chunk("navigation"), chunk(MARGIN)], registry, source_type="IR") == []


def test_ir_narrative_candidates_retain_two_exact_citations_and_need_approval(db):
    session, doc, registry = db
    registry[0].metric_key = "gross_margin"; registry[0].canonical_unit = "decimal"
    session.scalar(select(DocumentChunk)).text = ANCHOR
    session.add(DocumentChunk(document_id=doc.id, chunk_index=71, text=MARGIN))
    session.commit()
    out = asyncio.run(service.KPIExtractionService().extract_document(session, doc, mode="deterministic-only"))
    assert len(out) == 1
    assert out[0].normalized_value == Decimal("0.627")
    assert out[0].status == "pending_approval"
    assert out[0].source_locator["context"]["quote"] in ANCHOR
    assert out[0].source_locator["quote"] in MARGIN
    assert session.scalar(select(FinancialFact)) is None


def test_explicit_currency_and_period_narrative_generalizes_beyond_sample():
    text = "Revenue in FY2024 was EUR 123.4 million."
    out = parser.extract([chunk(text)], [row(unit="EUR")], source_type="IR")
    assert len(out) == 1
    assert out[0]["raw_value"] == "123.4"
    assert out[0]["period"] == "FY2024"
    assert out[0]["quote"] in text
    assert parser.extract([chunk(text)], [row(unit="USD")], source_type="IR") == []
    assert parser.extract([chunk(text.replace("EUR", "$"))], [row(unit="USD")], source_type="IR") == []
    assert parser.extract([chunk("We expect " + text)], [row(unit="EUR")], source_type="IR") == []
    assert parser.extract([chunk("We EXPECT " + text)], [row(unit="EUR")], source_type="IR") == []


@pytest.mark.parametrize("scale", ["million", "billion"])
@pytest.mark.parametrize("suffix", [", up from last year.", ", according to our forecast.", ", according to our GUIDANCE."])
def test_money_sentence_never_truncates_decimal_or_hides_suffix(db, scale, suffix):
    session, doc, _ = db
    text = f"Revenue in FY2024 was USD 123.4 {scale}{suffix}"
    session.scalar(select(DocumentChunk)).text = text
    session.commit()
    # Conservative abstention on any unsupported trailing prose. The quote
    # must never shrink to 'USD 123', losing the scale or forecast qualifier.
    assert parser.extract([chunk(text)], [row()], source_type="IR") == []
    out = asyncio.run(service.KPIExtractionService().extract_document(session, doc, mode="deterministic-only"))
    assert out == []
    assert session.scalar(select(FinancialFact)) is None


@pytest.mark.parametrize("scale,multiplier", [("million", Decimal("1e6")), ("billion", Decimal("1e9"))])
@pytest.mark.parametrize("value", ["123.4", "123,4", "123"])
@pytest.mark.parametrize("ending", [".", "", "\n"])
def test_money_decimal_scale_and_final_period_preserved(db, scale, multiplier, value, ending):
    session, doc, _ = db
    text = f"Revenue in FY2024 was USD {value} {scale}{ending}"
    session.scalar(select(DocumentChunk)).text = text
    session.commit()
    out = asyncio.run(service.KPIExtractionService().extract_document(session, doc, mode="deterministic-only"))
    assert len(out) == 1
    assert out[0].normalized_value == Decimal(value.replace(",", ".")) * multiplier
    assert scale in out[0].source_locator["quote"]
    assert value in out[0].source_locator["quote"]
    assert out[0].source_locator["quote"] in text
    assert session.scalar(select(FinancialFact)) is None


def test_new_conflict_demotes_existing_pending_without_changing_approved_or_rejected(db):
    session, doc, _ = db
    session.scalar(select(DocumentChunk)).text = "Revenue in FY2025 was USD 12."
    session.commit()
    initial = asyncio.run(service.KPIExtractionService().extract_document(session, doc, mode="deterministic-only"))
    assert initial[0].status == "pending_approval"
    original_id = initial[0].id
    session.add(DocumentChunk(document_id=doc.id, chunk_index=71, text="Revenue in FY2025 was USD 99."))
    session.commit()
    updated = asyncio.run(service.KPIExtractionService().extract_document(session, doc, mode="deterministic-only"))
    assert len(updated) == 2
    assert all(c.status == "needs_review" for c in updated)
    assert next(c for c in updated if c.id == original_id).reconciliation_status == "needs_review"
    # Human decisions are immutable to this automatic conflict reconciliation.
    initial[0].status = "approved"
    updated[1].status = "rejected"
    session.commit()
    again = asyncio.run(service.KPIExtractionService().extract_document(session, doc, mode="deterministic-only"))
    assert {c.status for c in again} == {"approved", "rejected"}


def test_xbrl_currency_prefix_must_resolve_official_namespace():
    valid = XML
    assert len(parser.extract([chunk(valid)], [row()], source_type="SEC", cik="123")) == 1
    invalid = valid.replace('http://www.xbrl.org/2003/iso4217', 'https://example.invalid/private-units')
    assert parser.extract([chunk(invalid)], [row()], source_type="SEC", cik="123") == []
    assert parser.extract([chunk(XML.replace(' xmlns:iso4217="http://www.xbrl.org/2003/iso4217"', ""))], [row()], source_type="SEC", cik="123") == []


def test_xbrl_nested_namespace_rebinding_abstains_and_alias_resolves_uri():
    shadow = XML.replace('<x:measure>', '<x:measure xmlns:iso4217="https://example.invalid/private-units">')
    assert parser.extract([chunk(shadow)], [row()], source_type="SEC", cik="123") == []
    alias = XML.replace('xmlns:iso4217=', 'xmlns:money=').replace('iso4217:USD', 'money:USD')
    assert len(parser.extract([chunk(alias)], [row()], source_type="SEC", cik="123")) == 1
