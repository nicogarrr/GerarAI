from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, or_, select

import main
from app.core.database import SessionLocal, init_db
from app.data.company_master import COMPANY_MASTER
from app.models import Company, ExternalClaim, FinancialFact, MemoryItem, NewsEvent, ThesisChange
from app.seed import seed
from app.services.manual_transcript_import_service import ManualTranscriptImportService
from app.services.source_auditor import SourceAuditor
from app.valuation import DCFInputs, ReverseDCFInputs, run_dcf, solve_required_growth

TEST_NEWS_SOURCES = {"manual_test", "test_feed", "workflow_test_feed"}
TEST_NEWS_PATTERNS = [
    "%example.com/msft-%",
    "%announces a large share offering%",
    "%MSFT wins major customer contract%",
    "%MSFT cuts guidance after earnings miss%",
]
TEST_MEMORY_PATTERNS = ["%Azure AI demand sigue sosteniendo premium cloud growth%"]


def cleanup_news_test_artifacts() -> None:
    init_db()
    db = SessionLocal()
    try:
        news_filters = [
            NewsEvent.source.in_(TEST_NEWS_SOURCES),
            *(NewsEvent.url.like(pattern) for pattern in TEST_NEWS_PATTERNS),
            *(NewsEvent.title.like(pattern) for pattern in TEST_NEWS_PATTERNS),
        ]
        news_events = db.scalars(select(NewsEvent).where(or_(*news_filters))).all()
        summaries = [event.summary for event in news_events if event.summary]

        if summaries:
            db.execute(delete(ExternalClaim).where(ExternalClaim.claim.in_(summaries)))

        db.execute(
            delete(MemoryItem).where(
                MemoryItem.source_type == "chat",
                or_(*(MemoryItem.content.like(pattern) for pattern in TEST_MEMORY_PATTERNS)),
            )
        )
        db.execute(
            delete(FinancialFact).where(
                FinancialFact.source_type == "test_sec",
                FinancialFact.metric == "revenue",
                FinancialFact.period == "FY2025",
            )
        )
        db.execute(
            delete(ThesisChange).where(
                or_(*(ThesisChange.summary.like(pattern) for pattern in TEST_NEWS_PATTERNS))
            )
        )
        for event in news_events:
            db.delete(event)

        db.commit()
    finally:
        db.close()


@pytest.fixture(autouse=True)
def clean_news_artifacts_between_tests():
    cleanup_news_test_artifacts()
    yield
    cleanup_news_test_artifacts()


class FakeFMPClient:
    async def company_profile(self, ticker: str):
        return [{"symbol": ticker, "price": 20.0}]

    async def income_statement(self, ticker: str, limit: int = 10):
        return [
            {
                "date": "2025-12-31",
                "calendarYear": "2025",
                "period": "FY",
                "revenue": 1000,
                "grossProfit": 650,
                "operatingIncome": 250,
                "netIncome": 180,
                "ebitda": 300,
                "epsdiluted": 1.8,
                "weightedAverageShsOutDil": 100,
            },
            {
                "date": "2024-12-31",
                "calendarYear": "2024",
                "period": "FY",
                "revenue": 800,
                "grossProfit": 500,
                "operatingIncome": 190,
                "netIncome": 140,
                "ebitda": 230,
                "epsdiluted": 1.4,
                "weightedAverageShsOutDil": 100,
            },
        ]

    async def balance_sheet(self, ticker: str, limit: int = 10):
        return [
            {
                "date": "2025-12-31",
                "calendarYear": "2025",
                "period": "FY",
                "cashAndCashEquivalents": 100,
                "totalDebt": 200,
                "totalAssets": 1500,
                "totalLiabilities": 700,
                "totalStockholdersEquity": 800,
            }
        ]

    async def cash_flow(self, ticker: str, limit: int = 10):
        return [
            {
                "date": "2025-12-31",
                "calendarYear": "2025",
                "period": "FY",
                "operatingCashFlow": 300,
                "capitalExpenditure": -50,
                "freeCashFlow": 250,
                "commonStockRepurchased": -25,
                "dividendsPaid": -10,
            }
        ]

    async def ratios(self, ticker: str, limit: int = 10):
        return [
            {
                "date": "2025-12-31",
                "calendarYear": "2025",
                "period": "FY",
                "grossProfitMargin": 0.65,
                "operatingProfitMargin": 0.25,
                "netProfitMargin": 0.18,
                "debtEquityRatio": 0.25,
            }
        ]


def test_research_api_core_flow():
    seed()
    client = TestClient(main.app)
    token = client.get("/api/csrf-token").json()["csrf_token"]
    client.headers.update({"x-csrf-token": token})

    companies = client.get("/api/companies")
    assert companies.status_code == 200
    assert len(companies.json()) >= len(COMPANY_MASTER)

    portfolio = client.get("/api/portfolio/summary")
    assert portfolio.status_code == 200
    assert {"total_value", "equity_value", "cash", "alerts"}.issubset(portfolio.json())

    valuation = client.get("/api/valuation/ASTS")
    assert valuation.status_code == 200
    assert valuation.json()["ticker"] == "ASTS"
    assert valuation.json()["status"] == "insufficient_data"
    assert valuation.json()["publishable"] is False
    assert valuation.json()["expected_value"] is None
    assert valuation.json()["trace"]["engine"] == "pre_revenue"

    thesis = client.post("/api/thesis/generate", json={"ticker": "ASTS", "force_new_version": True})
    assert thesis.status_code == 200
    assert thesis.json()["status"] in {"final", "draft_failed_audit", "insufficient_data", "draft"}
    assert f"Tesis de ASTS — v{thesis.json()['version']}" in thesis.json()["thesis_markdown"]

    chat = client.post("/api/chat", json={"question": "Que pasa con ASTS?", "ticker": "ASTS"})
    assert chat.status_code == 200
    assert "ASTS" in chat.json()["answer"]


def test_memory_api_tracks_claims_evidence_sections_and_sessions():
    seed()
    client = TestClient(main.app)
    token = client.get("/api/csrf-token").json()["csrf_token"]
    client.headers.update({"x-csrf-token": token})
    token = client.get("/api/csrf-token").json()["csrf_token"]
    client.headers.update({"x-csrf-token": token})

    thesis = client.post("/api/thesis/generate", json={"ticker": "MSFT", "force_new_version": True})
    assert thesis.status_code == 200
    thesis_payload = thesis.json()

    section = client.post(
        f"/api/memory/thesis/MSFT/versions/{thesis_payload['id']}/sections",
        json={
            "section_key": "why-now",
            "title": "Why now",
            "body": "Azure AI demand is the key near-term variable.",
            "status": "active",
            "order_index": 1,
        },
    )
    assert section.status_code == 200
    assert section.json()["section_key"] == "why-now"

    claim = client.post(
        "/api/memory/claims",
        json={
            "ticker": "MSFT",
            "thesis_version_id": thesis_payload["id"],
            "statement": "Azure AI demand can sustain premium cloud growth.",
            "claim_type": "growth_driver",
            "materiality_score": 9,
        },
    )
    assert claim.status_code == 200
    claim_payload = claim.json()
    assert claim_payload["status"] == "unverified"

    source = client.post(
        "/api/sources/transcripts/import-text",
        json={
            "ticker": "MSFT",
            "title": f"MSFT evidence fixture {uuid4().hex}",
            "text": "Management reported durable Azure AI demand and disciplined capital expenditure. "
            * 10,
            "source_url": "https://www.microsoft.com/investor",
            "period": "Q1",
        },
    )
    assert source.status_code == 200
    source_document_id = source.json()["document_id"]

    documents = client.get("/api/sources/documents?ticker=MSFT&scope=all&include_chunks=true")
    assert documents.status_code == 200
    document_payload = next(
        item for item in documents.json() if item["id"] == source_document_id
    )
    chunk_payload = document_payload["chunks"][0]

    evidence = client.post(
        f"/api/memory/claims/{claim_payload['id']}/evidence",
        json={
            "document_id": document_payload["id"],
            "document_chunk_id": chunk_payload["id"],
            "evidence_type": "supports",
            "summary": "Management commentary points to durable Azure AI demand.",
            "source_url": "https://www.microsoft.com/investor",
            "source_tier": "primary",
        },
    )
    assert evidence.status_code == 200

    updated_claim = client.get(f"/api/memory/claims/{claim_payload['id']}")
    assert updated_claim.status_code == 200
    assert updated_claim.json()["status"] == "supported"
    assert (
        updated_claim.json()["evidence"][0]["source_tier"]
        == "tier_3_transcript"
    )
    assert updated_claim.json()["evidence"][0]["document_id"] == document_payload["id"]
    assert updated_claim.json()["evidence"][0]["document_chunk_id"] == chunk_payload["id"]

    contradiction = client.post(
        f"/api/memory/claims/{claim_payload['id']}/evidence",
        json={
            "evidence_type": "contradicts",
            "summary": "A later source suggests Azure growth may be decelerating.",
            "source_url": "https://www.microsoft.com/investor",
            "source_tier": "primary",
        },
    )
    assert contradiction.status_code == 200

    contradicted_claim = client.get(f"/api/memory/claims/{claim_payload['id']}")
    assert contradicted_claim.status_code == 200
    assert contradicted_claim.json()["status"] == "contradicted"
    assert len(contradicted_claim.json()["evidence"]) == 2

    changes = client.get("/api/memory/thesis/MSFT/changes")
    assert changes.status_code == 200
    auto_change = next(
        item
        for item in changes.json()
        if item["affected_claim_ids"] == [claim_payload["id"]]
    )
    assert auto_change["change_type"] == "claim_contradiction"
    assert auto_change["impact_direction"] == "negative"
    assert auto_change["requires_review"] is True
    assert auto_change["affected_claim_ids"] == [claim_payload["id"]]

    manual_change = client.post(
        "/api/memory/thesis/changes",
        json={
            "ticker": "MSFT",
            "change_type": "material_update",
            "impact_direction": "mixed",
            "materiality_score": 7,
            "summary": "Azure AI remains strong but capex intensity needs monitoring.",
            "affected_metrics": ["capex", "fcf_margin"],
            "requires_review": True,
        },
    )
    assert manual_change.status_code == 200
    assert manual_change.json()["affected_metrics"] == ["capex", "fcf_margin"]

    material_news = client.post(
        "/api/news/manual",
        json={
            "text": (
                "Microsoft (MSFT) announces a large share offering and cuts revenue guidance, "
                "raising dilution and fcf margin concerns for the current Microsoft thesis."
            ),
            "source": "manual_test",
            "url": "https://www.microsoft.com/investor",
        },
    )
    assert material_news.status_code == 200
    assert material_news.json()["requires_update"] is True
    events = client.get("/api/news")
    assert events.status_code == 200
    assert events.json()[0]["url"] == "https://www.microsoft.com/investor"

    news_changes = client.get("/api/memory/thesis/MSFT/changes")
    assert news_changes.status_code == 200
    assert any(
        item["change_type"] == "news_potential_invalidation"
        and item["impact_direction"] == "negative"
        and "guidance" in item["affected_metrics"]
        for item in news_changes.json()
    )

    unique_suffix = uuid4().hex
    contract_url = f"https://www.microsoft.com/investor/news/msft-contract-{unique_suffix}"
    contract_title = f"Microsoft wins major customer contract and raises revenue outlook {unique_suffix}"
    contract_text = f"New contract award improves backlog conversion and revenue timing {unique_suffix}."
    batch = client.post(
        "/api/news/ingest",
        json={
            "source": "test_feed",
            "items": [
                        {
                            "ticker": "MSFT",
                            "title": contract_title,
                            "text": contract_text,
                            "url": contract_url,
                            "source": "test_feed",
                        },
                        {
                            "ticker": "MSFT",
                            "title": contract_title,
                            "text": contract_text,
                            "url": contract_url,
                            "source": "test_feed",
                        },
            ],
        },
    )
    assert batch.status_code == 200
    assert batch.json()["created"] == 1
    assert batch.json()["skipped_duplicates"] == 1
    assert batch.json()["requires_update"] == 1

    daily = client.post(
        "/api/workflows/DailyResearchWorkflow/run",
        json={
            "params": {
                "source": "workflow_test_feed",
                "news_items": [
                        {
                            "ticker": "MSFT",
                            "title": f"MSFT cuts guidance after earnings miss {unique_suffix}",
                            "text": f"The earnings miss and guidance cut affect revenue growth and fcf margin {unique_suffix}.",
                            "url": f"https://example.com/msft-guidance-cut-{unique_suffix}",
                        }
                ],
            }
        },
    )
    assert daily.status_code == 200
    assert daily.json()["status"] == "completed"
    assert daily.json()["result"]["created"] == 1

    session = client.post(
        "/api/memory/research-sessions",
        json={
            "ticker": "MSFT",
            "title": "Azure AI demand review",
            "question": "Is Azure AI demand still strengthening the thesis?",
            "claim_ids": [claim_payload["id"]],
        },
    )
    assert session.status_code == 200

    memory = client.post(
        "/api/memory/memory-items",
        json={
            "ticker": "MSFT",
            "research_session_id": session.json()["id"],
            "scope": "company",
            "memory_type": "watch_item",
            "importance": 8,
            "content": "Recheck Azure AI growth commentary after the next earnings call.",
        },
    )
    assert memory.status_code == 200
    assert memory.json()["memory_type"] == "watch_item"

    db = SessionLocal()
    try:
        msft = db.scalar(select(Company).where(Company.ticker == "MSFT"))
        assert msft is not None
        existing_revenue = db.scalar(
            select(FinancialFact).where(
                FinancialFact.company_id == msft.id,
                FinancialFact.metric == "revenue",
                FinancialFact.period == "FY2025",
            )
        )
        if existing_revenue is None:
            db.add(
                FinancialFact(
                    company_id=msft.id,
                    metric="revenue",
                    value=Decimal("1000"),
                    unit="USDm",
                    period="FY2025",
                    fiscal_year=2025,
                    source_type="test_sec",
                    confidence=Decimal("0.95"),
                )
            )
            db.commit()
    finally:
        db.close()

    # El cerebro es SOLO LECTURA: "Recuerda ..." ya no escribe desde el chat;
    # la memoria la crea el usuario por la vía de memoria (aquí, sembrada).
    db = SessionLocal()
    try:
        company_id = db.scalar(select(Company.id).where(Company.ticker == "MSFT"))
        db.add(MemoryItem(
            company_id=company_id, scope="company", memory_type="watch_item",
            importance=8, status="active", source_type="user",
            content="Vigilar si Azure AI demand sigue sosteniendo premium cloud growth.",
        ))
        db.commit()
    finally:
        db.close()

    source_aware_chat = client.post(
        "/api/chat",
        json={
            "ticker": "MSFT",
            "scope": "company",
            "question": (
                "Recuerda vigilar si Azure AI demand sigue sosteniendo premium cloud growth. "
                "Que evidencia tienes sobre MSFT?"
            ),
        },
    )
    assert source_aware_chat.status_code == 200
    chat_payload = source_aware_chat.json()
    # La respuesta visible es prosa natural; la estructura vive en `sections`.
    assert "HECHO" not in chat_payload["answer"]
    section_keys = {section["key"] for section in chat_payload["sections"]}
    assert {"facts", "user_hypotheses", "unverified_claims", "inferences"} <= section_keys
    hypotheses = next(s for s in chat_payload["sections"] if s["key"] == "user_hypotheses")
    assert "Azure AI demand" in hypotheses["body"]
    source_types = {source["type"] for source in chat_payload["sources"]}
    assert {"thesis_version", "financial_fact", "claim", "claim_evidence", "memory_item"} <= source_types
    # El cerebro es SOLO LECTURA: ni "Recuerda ..." escribe memoria desde el chat.
    assert "memory_writeback" not in source_types

    db = SessionLocal()
    try:
        stored_chat_memory = db.scalar(
            select(MemoryItem).where(
                MemoryItem.source_type == "chat",
                MemoryItem.content.like("%Azure AI demand%"),
            )
        )
        assert stored_chat_memory is None
    finally:
        db.close()

    sections = client.get("/api/memory/thesis/MSFT/sections")
    assert sections.status_code == 200
    assert any(item["section_key"] == "why-now" for item in sections.json())


def test_source_auditor_blocks_unsourced_material_claims():
    audit = SourceAuditor().audit(
        claims=[{"claim": "Revenue grew 18% YoY", "material": True, "source_id": None}],
        calculation_trace={"method": "test"},
    )

    assert not audit.passed
    assert audit.unsupported_claims == ["Revenue grew 18% YoY"]


def test_dcf_and_reverse_dcf_are_deterministic():
    result = run_dcf(
        DCFInputs(
            revenue=1000,
            revenue_growth=0.10,
            fcf_margin=0.20,
            wacc=0.09,
            terminal_growth=0.03,
            net_debt=100,
            shares_outstanding=100,
        )
    )

    assert result.value_per_share > 0
    assert result.trace["method"] == "fcff_dcf"
    assert len(result.forecast) == 5

    solved = solve_required_growth(
        ReverseDCFInputs(
            market_price=50,
            revenue=1000,
            fcf_margin=0.18,
            wacc=0.10,
            terminal_growth=0.03,
            net_debt=100,
            shares_outstanding=100,
        )
    )

    assert abs(solved["solved_value_per_share"] - 50) < 0.01


def test_manual_import_creates_document_chunks_and_transcript():
    init_db()
    seed()
    db = SessionLocal()
    try:
        result = ManualTranscriptImportService().import_text(
            db=db,
            ticker="MSFT",
            title="MSFT Q1 call transcript",
            text="Management discussed Azure AI demand and capex discipline. " * 20,
            source_url="https://www.microsoft.com/investor",
            period="Q1",
        )

        assert result["ticker"] == "MSFT"
        assert result["document_id"] > 0
        assert result["transcript_id"] > 0
        assert result["chunks"] >= 1
    finally:
        db.close()


def test_ibkr_xml_import_endpoint_ingests_positions_cash_and_trades(monkeypatch):
    from datetime import date
    from types import SimpleNamespace

    from app.api.routes import portfolio as route
    from app.core.database import get_db
    from app.models import Tenant

    init_db()
    with SessionLocal() as setup:
        tenant = Tenant(external_id=f"ibkr-http-{uuid4().hex}", name="Isolated IBKR HTTP")
        setup.add(tenant)
        setup.commit()
        owner_id = tenant.id
    configured = SimpleNamespace(ibkr_flex_tenant_id=owner_id, ibkr_flex_account_id="U-HTTP-TEST")
    monkeypatch.setattr(route, "get_settings", lambda: configured)

    def owner_db():
        with SessionLocal() as db:
            db.info["tenant_id"] = owner_id
            yield db

    previous = main.app.dependency_overrides.get(get_db)
    main.app.dependency_overrides[get_db] = owner_db
    day = date.today().isoformat()
    xml = f"""
    <FlexQueryResponse><FlexStatements><FlexStatement accountId="U-HTTP-TEST" toDate="{day}">
      <OpenPositions>
        <OpenPosition accountId="U-HTTP-TEST" symbol="AAPL" position="2" markPrice="200" positionValue="400" costBasisPrice="150" currency="USD" reportDate="{day}" fifoPnlUnrealized="100" />
      </OpenPositions>
      <CashReports>
        <CashReport accountId="U-HTTP-TEST" currency="USD" toDate="{day}" endingCash="1234.56" settledCash="1200" />
      </CashReports>
      <Trades>
        <Trade accountId="U-HTTP-TEST" tradeID="test-trade-1" symbol="AAPL" buySell="BUY" quantity="2" tradePrice="150" ibCommission="-1" currency="USD" tradeDate="{day}" />
      </Trades>
    </FlexStatement></FlexStatements></FlexQueryResponse>
    """
    try:
        client = TestClient(main.app)
        token = client.get("/api/csrf-token").json()["csrf_token"]
        client.headers.update({"x-csrf-token": token})
        response = client.post("/api/portfolio/import/ibkr/xml", json={"xml": xml})
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "imported"
        assert payload["positions_imported"] == 1
        assert payload["cash_imported"] == 1
        assert payload["trades_imported"] == 1
        replay = client.post("/api/portfolio/import/ibkr/xml", json={"xml": xml})
        assert replay.status_code == 200
        assert replay.json()["trades_imported"] == 0
        configured.ibkr_flex_tenant_id = owner_id + 1
        for endpoint, body in [("/api/portfolio/import/ibkr/xml", {"xml": xml}), ("/api/portfolio/import/ibkr", None)]:
            assert client.post(endpoint, json=body).status_code == 403
    finally:
        if previous is None:
            main.app.dependency_overrides.pop(get_db, None)
        else:
            main.app.dependency_overrides[get_db] = previous


def test_fmp_refresh_normalizes_facts_and_valuation_uses_them(monkeypatch):
    from app.api.routes import companies as companies_route

    init_db()
    seed()
    monkeypatch.setattr(companies_route, "FMPClient", FakeFMPClient)
    client = TestClient(main.app)
    token = client.get("/api/csrf-token").json()["csrf_token"]
    client.headers.update({"x-csrf-token": token})
    token = client.get("/api/csrf-token").json()["csrf_token"]
    client.headers.update({"x-csrf-token": token})

    refresh = client.post("/api/companies/MSFT/refresh/fmp")
    assert refresh.status_code == 200
    payload = refresh.json()
    assert payload["status"] == "ingested"
    assert payload["facts_imported"] >= 20
    assert payload["valuation_input_ready"] is True

    facts = client.get("/api/companies/MSFT/facts?metric=revenue")
    assert facts.status_code == 200
    revenue_facts = facts.json()
    assert revenue_facts[0]["metric"] == "revenue"
    assert revenue_facts[0]["source_type"] == "FMP"

    valuation = client.get("/api/valuation/MSFT")
    assert valuation.status_code == 200
    payload = valuation.json()
    trace = payload["trace"]
    # An FMP refresh gives the fundamentals, not the discount rate: with no
    # dated WACC persisted, the DCF is an orientation and says so, instead of
    # being published as final on the strength of a tag default.
    assert payload["status"] == "partial"
    assert payload["publishable"] is False
    assert "traceable_wacc" in payload["publication_blockers"]
    assert payload["expected_value"] is not None
    assert trace["input_source"] == "financial_facts"
    assert trace["fact_ids"]["revenue"] == revenue_facts[0]["id"]
    assert "bootstrap_notice" not in trace
    assert trace["engine"] == "standard_dcf"
    assert "snapshot" in trace

    thesis = client.post("/api/thesis/generate", json={"ticker": "MSFT", "force_new_version": True})
    assert thesis.status_code == 200
    thesis_payload = thesis.json()
    assert "Fuente de los inputs de valoración: Datos financieros" in thesis_payload["thesis_markdown"]
    assert "| Ingresos |" in thesis_payload["thesis_markdown"]
    assert f"Tesis de MSFT — v{thesis_payload['version']}" in thesis_payload["thesis_markdown"]
    assert thesis_payload["status"] == "draft"
    # F7: la confianza se deriva de la evidencia (ya no la constante 55). Con
    # valoracion no publicable cae en la banda 35-75 (floor/ceiling de _confidence_score).
    assert 35 <= thesis_payload["data_confidence_score"] <= 75
    # Los KPIs del marco sin dato se declaran «sin dato (motivo)», sin clave interna.
    assert "Datos operativos del marco:" in thesis_payload["thesis_markdown"]
    assert "sin dato (" in thesis_payload["thesis_markdown"]
    assert "Datos operativos del marco: todos con dato" not in thesis_payload["thesis_markdown"]


def test_fmp_refresh_402_returns_actionable_message(monkeypatch):
    """El plan free de FMP no cubre no-US: 402 -> 424 con mensaje claro (B30)."""
    import httpx

    from app.api.routes import companies as companies_route

    class DeniedFMPClient:
        async def income_statement(self, ticker: str, limit: int = 5):
            request = httpx.Request(
                "GET", "https://financialmodelingprep.com/stable/income-statement"
            )
            response = httpx.Response(402, request=request)
            raise httpx.HTTPStatusError(
                "payment required", request=request, response=response
            )

    init_db()
    seed()
    monkeypatch.setattr(companies_route, "FMPClient", DeniedFMPClient)
    client = TestClient(main.app)
    token = client.get("/api/csrf-token").json()["csrf_token"]
    client.headers.update({"x-csrf-token": token})
    # El endpoint muta estado: exige token CSRF (VAL-SEC-001).
    token = client.get("/api/csrf-token").json()["csrf_token"]
    client.headers.update({"x-csrf-token": token})

    refresh = client.post("/api/companies/MSFT/refresh/fmp")
    assert refresh.status_code == 424
    detail = refresh.json()["detail"]
    assert "plan gratuito de FMP" in detail
    # La URL con la api key nunca se filtra en el detalle.
    assert "apikey" not in detail
    assert "http" not in detail.lower()
