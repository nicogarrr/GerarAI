from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes.research_assistant import AssistantRequest, AssistantResponse
from app.models.entities import Base, Company, Document, FinancialFact, NewsEvent, ResearchReview, Tenant
from app.services.research_assistant_service import answer, guide_context


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    engine.dispose()


def setup(db):
    a = Tenant(external_id="assistant-a", name="A", status="active", metadata_={})
    b = Tenant(external_id="assistant-b", name="B", status="active", metadata_={})
    company = Company(ticker="ASTS", name="AST SpaceMobile", exchange="NASDAQ", currency="USD",
                      company_type="holding", valuation_model="unassigned")
    db.add_all((a, b, company))
    db.flush()
    db.info["tenant_id"] = a.id
    return a, b, company


def test_contract_no_data_and_no_writeback(db):
    a, b, company = setup(db)
    before = db.query(ResearchReview).count()
    response = AssistantResponse.model_validate(answer(db, AssistantRequest(
        mode="explore", question="remember this idea", ticker="ASTS")))
    assert response.status == "insufficient_data"
    assert response.citations == [] and response.writeback is False
    assert db.query(ResearchReview).count() == before
    with pytest.raises(ValueError):
        AssistantRequest(mode="guide", question="What now?")


def test_tenant_isolation_ticket_binding_and_cited_rows(db):
    a, b, company = setup(db)
    doc = Document(tenant_id=a.id, company_id=company.id, title="Company filing",
                   source_type="company_ir", source_url="https://example.com/filing")
    other_doc = Document(tenant_id=b.id, company_id=company.id, title="Other's filing",
                         source_type="company_ir", source_url="https://example.com/private")
    db.add(doc)
    db.flush()
    db.info["tenant_id"] = b.id
    db.add(other_doc)
    db.flush()
    db.info["tenant_id"] = a.id
    db.add(FinancialFact(tenant_id=a.id, company_id=company.id, metric="revenue",
                         value=Decimal("123"), unit="USD", period="FY2025", fiscal_year=2025,
                         source_id=doc.id, source_type="company_ir"))

    db.add(NewsEvent(tenant_id=a.id, company_id=company.id, title="ASTS ITU filing reported",
                     source="Publisher", url="https://example.com/article",
                     date=datetime(2026, 9, 24, tzinfo=UTC), metadata_={"date_source": "gdelt_first_seen", "source_headline": "ASTS ITU filing reported"}))

    review = ResearchReview(tenant_id=a.id, company_id=company.id, review_type="news", title="Review ITU",
                            summary="Check original ITU filing", status="open")
    other_review = ResearchReview(tenant_id=b.id, company_id=company.id, review_type="news", title="Private",
                                  summary="Private review", status="open")
    db.add(review)
    db.commit()
    db.info["tenant_id"] = b.id
    db.add(FinancialFact(tenant_id=b.id, company_id=company.id, metric="revenue",
                         value=Decimal("999"), unit="USD", period="FY2025", fiscal_year=2025,
                         source_id=other_doc.id, source_type="company_ir"))
    db.add(NewsEvent(tenant_id=b.id, company_id=company.id, title="Private news",
                     source="Other", url="https://example.com/private-news",
                     date=datetime(2026, 9, 24, tzinfo=UTC), metadata_={"date_source": "source"}))
    db.add(other_review)
    db.commit()
    db.info["tenant_id"] = a.id
    response = AssistantResponse.model_validate(answer(db, AssistantRequest(
        mode="guide", question="What does the ITU filing say?", ticker="ASTS", review_id=review.id)))
    assert response.review_id == review.id and response.writeback is False
    assert response.status == "answered"
    assert any(c.kind == "news_event" for c in response.citations)
    assert all(c.kind != "financial_fact" for c in response.citations)
    assert "999" not in response.answer and "Private" not in response.answer
    assert all(cid in {c.id for c in response.citations} for sec in response.sections for cid in sec.citation_ids)
    context = guide_context(db, "ASTS")
    assert context["review_id"] == review.id
    assert [r["id"] for r in context["open_reviews"]] == [review.id]
    with pytest.raises(LookupError):
        answer(db, AssistantRequest(mode="guide", question="What now?", ticker="ASTS", review_id=other_review.id))


def test_relevant_filing_chunk_beats_six_unrelated_facts(db):
    from app.models.entities import DocumentChunk

    tenant, _, company = setup(db)
    for i in range(6):
        doc = Document(tenant_id=tenant.id, company_id=company.id, title=f"Annual revenue {i}",
                       source_type="company_ir", source_url=f"https://example.com/revenue/{i}")
        db.add(doc)
        db.flush()
        db.add(FinancialFact(tenant_id=tenant.id, company_id=company.id, metric="revenue",
                             value=Decimal(str(i + 10)), unit="USD", period="FY2025", fiscal_year=2025,
                             source_id=doc.id, source_type="company_ir"))
    filing = Document(tenant_id=tenant.id, company_id=company.id, title="D-BLUEBIRD ITU filing",
                      source_type="regulatory", source_url="https://example.com/itu-filing",
                      published_at=datetime(2026, 9, 24, tzinfo=UTC))
    db.add(filing)
    db.flush()
    db.add(DocumentChunk(tenant_id=tenant.id, document_id=filing.id, chunk_index=0,
                         text="ITU filing D-BLUEBIRD describes the constellation registration.", token_count=10))
    db.commit()
    response = AssistantResponse.model_validate(answer(db, AssistantRequest(
        mode="guide", ticker="ASTS", question="¿Qué dice el filing ITU D-BLUEBIRD?")))
    assert response.status == "answered"
    assert any(c.kind == "document_chunk" and "ITU" in c.source for c in response.citations)
    assert all(c.kind != "financial_fact" for c in response.citations)
    missing = AssistantResponse.model_validate(answer(db, AssistantRequest(
        mode="explore", ticker="ASTS", question="¿Qué pasó con el propulsor xenón?")))
    assert missing.status == "insufficient_data"
    assert missing.citations == [] and missing.missing_data


def test_connector_summary_cannot_become_attributed_headline(db, monkeypatch):
    from app.schemas import NewsIngestResponse
    from app.services.connectors.base import ConnectorItem, ConnectorResult
    from app.services.feed_ingestion_service import FeedIngestionService
    from app.services.news_service import NewsService

    tenant, _, company = setup(db)
    stamp = datetime(2026, 9, 24, tzinfo=UTC)

    def ingest_stub(self, session, items, default_source="feed", connector=None,
                    date_source_label=None, source_headline=None,
                    news_lane=None, macro_theme=None, detect_company=True,
                    llm_deadline=None):
        for item in items:
            metadata = {"date_source": date_source_label or "source"}
            if connector:
                metadata["connector"] = connector
            headline = source_headline or item.title
            if headline:
                metadata["source_headline"] = headline
            if news_lane:
                metadata["news_lane"] = news_lane
            if macro_theme:
                metadata["macro_theme"] = macro_theme
            session.add(NewsEvent(tenant_id=tenant.id, company_id=company.id,
                                  title=f"ASTS {item.title} {item.text}", source=item.source,
                                  url=item.url, date=item.published_at,
                                  metadata_=metadata))
        session.commit()
        return NewsIngestResponse(status="ingested", received=len(items), created=len(items),
                                  skipped_duplicates=0, requires_update=0, events=[])

    monkeypatch.setattr(NewsService, "ingest_news_items", ingest_stub)
    result = ConnectorResult(source="rss", items=[
        ConnectorItem(source="Publisher", title="Company update", summary="New ITU filing",
                      url="https://publisher.example/update", ticker="ASTS", published_at=stamp),
        ConnectorItem(source="Publisher", title="ASTS ITU filing submitted", summary="Background",
                      url="https://publisher.example/filing", ticker="ASTS", published_at=stamp),
    ])
    FeedIngestionService().ingest_news_result(db, result, ticker="ASTS")
    response = AssistantResponse.model_validate(answer(db, AssistantRequest(
        mode="explore", question="What about ITU filing?", ticker="ASTS")))
    assert "ASTS ITU filing submitted" in response.answer
    assert "Company update New ITU filing" not in response.answer
    assert {c.url for c in response.citations if c.kind == "news_event"} == {"https://publisher.example/filing"}
    # Legacy composite title with no original headline is never attributed.
    db.add(NewsEvent(tenant_id=tenant.id, company_id=company.id, title="ASTS ITU filing legacy snippet",
                     source="Publisher", url="https://publisher.example/legacy", date=stamp,
                     metadata_={"date_source": "source"}))
    db.commit()
    response = AssistantResponse.model_validate(answer(db, AssistantRequest(
        mode="explore", question="What about ITU filing?", ticker="ASTS")))
    assert all(c.url != "https://publisher.example/legacy" for c in response.citations)
    assert all(n["title"] != "ASTS ITU filing legacy snippet" for n in guide_context(db, "ASTS")["latest_news"])


def test_guide_context_route_legacy_composite_degrades_without_500(db):
    from app.api.routes.research_assistant import GuideContextResponse, research_guide_context

    tenant, _, company = setup(db)
    db.add(NewsEvent(tenant_id=tenant.id, company_id=company.id,
                     title="ASTS Company update New ITU filing", source="Publisher",
                     url="https://publisher.example/article", date=datetime(2026, 9, 24, tzinfo=UTC),
                     metadata_={"date_source": "source"}))
    db.commit()
    # The actual route constructs the response_model, not just the service dict.
    response = research_guide_context(ticker="ASTS", db=db)
    payload = GuideContextResponse.model_validate(response).model_dump(mode="json")
    assert payload["latest_news"] == []
    assert payload["missing_data"]
    assert "Company update New ITU filing" not in str(payload)


def test_guide_context_prefilters_legacy_before_limit(db):
    tenant, _, company = setup(db)
    db.add(NewsEvent(tenant_id=tenant.id, company_id=company.id, title="ASTS ITU valid",
                     source="Publisher", url="https://publisher.example/valid",
                     date=datetime(2026, 9, 20, tzinfo=UTC),
                     metadata_={"date_source": "source", "source_headline": "ITU valid"}))
    for index in range(11):
        db.add(NewsEvent(tenant_id=tenant.id, company_id=company.id,
                         title=f"ASTS ITU composite {index}", source="Publisher",
                         url=f"https://publisher.example/legacy/{index}",
                         date=datetime(2026, 9, 24, tzinfo=UTC), metadata_={"date_source": "source"}))
    db.commit()
    from app.api.routes.research_assistant import research_guide_context
    result = research_guide_context(ticker="ASTS", db=db)
    assert len(result.latest_news) == 1
    assert result.latest_news[0].title == "ITU valid"
    assert result.missing_data


def test_general_question_lists_recent_sources_instead_of_no_data(db):
    from app.models.entities import DocumentChunk

    tenant, _, company = setup(db)
    filing = Document(tenant_id=tenant.id, company_id=company.id, title="Annual report",
                      source_type="company_ir", source_url="https://example.com/ar",
                      published_at=datetime(2026, 9, 24, tzinfo=UTC))
    db.add(filing)
    db.flush()
    db.add(DocumentChunk(tenant_id=tenant.id, document_id=filing.id, chunk_index=0,
                         text="Quarterly revenue grew.", token_count=4))
    db.commit()
    general = AssistantResponse.model_validate(answer(db, AssistantRequest(
        mode="explore", ticker="ASTS", question="¿Qué sabemos, qué falta y qué contradicciones hay?")))
    assert general.status == "answered"
    assert general.citations and all(c.kind == "document_chunk" for c in general.citations)
    assert "Pregunta general" in general.answer
    specific = AssistantResponse.model_validate(answer(db, AssistantRequest(
        mode="explore", ticker="ASTS", question="¿Qué pasó con el propulsor xenón?")))
    assert specific.status == "insufficient_data"


def test_thesis_style_question_lists_recent_sources(db):
    from app.models.entities import DocumentChunk

    tenant, _, company = setup(db)
    filing = Document(tenant_id=tenant.id, company_id=company.id, title="Annual report",
                      source_type="company_ir", source_url="https://example.com/ar",
                      published_at=datetime(2026, 9, 24, tzinfo=UTC))
    db.add(filing)
    db.flush()
    db.add(DocumentChunk(tenant_id=tenant.id, document_id=filing.id, chunk_index=0,
                         text="Quarterly revenue grew.", token_count=4))
    db.commit()
    for question in ("¿Qué dice la tesis?", "Cuéntame las últimas novedades", "análisis reciente"):
        r = AssistantResponse.model_validate(answer(db, AssistantRequest(
            mode="explore", ticker="ASTS", question=question)))
        assert r.status == "answered", question
        assert r.citations


def test_valuation_and_thesis_question_cites_draft_without_figures(db):
    from decimal import Decimal

    from app.models import ThesisVersion

    tenant, _, company = setup(db)
    db.add(ThesisVersion(
        tenant_id=tenant.id, company_id=company.id, version=11, status="draft",
        thesis_markdown="x", executive_summary="Borrador.", rating="watch",
        base_value=Decimal("120.5"), margin_of_safety=Decimal("0.123"),
    ))
    db.commit()
    r = AssistantResponse.model_validate(answer(db, AssistantRequest(
        mode="explore", ticker="ASTS", question="¿Cómo va la valoración y la tesis?")))
    assert r.status == "answered"
    assert r.citations[0].kind == "thesis_record"
    assert "borrador sin publicar" in r.answer and "v11" in r.answer
    assert "120" not in r.answer and "12,3" not in r.answer


def test_valuation_question_uses_published_thesis_figures_and_flags_newer_draft(db):
    from decimal import Decimal

    from app.models import ThesisVersion

    tenant, _, company = setup(db)
    from app.models import FundamentalModelVersion

    db.add(FundamentalModelVersion(
        tenant_id=tenant.id, company_id=company.id, version=1,
        engine_version="test", algorithm_version="test", framework_key="dcf",
        horizon_years=10, status="ok", publishable=True, input_fingerprint="input",
        forecast_fingerprint="forecast", market_snapshot_fingerprint="market",
        valuation_snapshot_fingerprint="valuation",
    ))
    db.add(ThesisVersion(
        tenant_id=tenant.id, company_id=company.id, version=10, status="published",
        thesis_markdown="x", executive_summary="Publicada.", rating="watch",
        base_value=Decimal("120.5"), margin_of_safety=Decimal("0.123"),
    ))
    db.add(ThesisVersion(
        tenant_id=tenant.id, company_id=company.id, version=11, status="draft",
        thesis_markdown="x", executive_summary="Borrador.", rating="watch",
        base_value=Decimal("999"), margin_of_safety=Decimal("0.5"),
    ))
    db.commit()
    r = AssistantResponse.model_validate(answer(db, AssistantRequest(
        mode="explore", ticker="ASTS", question="¿Cómo va la valoración y la tesis?")))
    assert "base $120.50" in r.answer and "12,3 %" in r.answer and "v10 publicada" in r.answer
    assert "fórmula no verificada" in r.answer
    assert "no es un margen comparable" in r.answer
    assert "borrador sin publicar" in r.answer
    assert "999" not in r.answer and "50,0" not in r.answer


def test_thesis_money_format_usd_en_us_other_es_es():
    from decimal import Decimal

    from app.services.research_assistant_service import _money

    assert _money(Decimal("1234.5"), "USD") == "$1,234.50"
    assert _money(Decimal("1234.5"), "EUR") == "1.234,50 EUR"


def test_selected_news_review_is_anchor_for_explain_without_unrelated_sources(db):
    tenant, other, company = setup(db)
    news = NewsEvent(tenant_id=tenant.id, company_id=company.id, title="Composite legacy display",
        summary="This is not primary evidence", source="Publisher", url="https://example.com/selected-news",
        date=datetime(2026,10,29,tzinfo=UTC), metadata_={"source_headline":"Memory supplier costs may rise", "date_source":"source"})
    db.add(news); db.flush()
    review = ResearchReview(tenant_id=tenant.id, company_id=company.id, title="Selected review",
        review_type="news", news_event_id=news.id, summary="Review summary is not evidence")
    db.add(review); db.flush()
    for question in ["explica la noticia", "explicame", "¿Qué dice esta revisión?"]:
        response = answer(db, AssistantRequest(mode="guide", ticker="ASTS", review_id=review.id, question=question))
        assert response["status"] == "answered"
        assert [c["id"] for c in response["citations"]] == [f"news_event:{news.id}"]
        assert response["citations"][0]["excerpt"] == "Memory supplier costs may rise"
        assert "Fuente primaria no consultada" in response["answer"]
        assert response["writeback"] is False
    response = answer(db, AssistantRequest(mode="guide", ticker="ASTS", review_id=review.id, question="What is the uranium debt covenant?"))
    assert response["status"] == "insufficient_data"
    db.info["tenant_id"] = other.id
    private_news = NewsEvent(tenant_id=other.id, company_id=company.id, title="Private headline",
        source="Private source", url="https://example.com/private", date=datetime(2026,10,29,tzinfo=UTC),
        metadata_={"source_headline":"Private headline", "date_source":"source"})
    db.add(private_news); db.flush()
    private_id = private_news.id
    db.info["tenant_id"] = tenant.id
    review.news_event_id = private_id
    db.flush()
    response = answer(db, AssistantRequest(mode="guide", ticker="ASTS", review_id=review.id, question="explica la noticia"))
    assert response["status"] == "insufficient_data"
