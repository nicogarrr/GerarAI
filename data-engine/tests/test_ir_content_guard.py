from app.services.ir_content_guard import normalized_digest, soft_404


def test_soft404_path_title_and_real_business_404_count():
    assert soft_404("https://bn.brookfield.com/page-not-found", "hello")
    assert soft_404("https://ir.test/x", "<title>Page not found</title><p>Sorry</p>", html=True)
    assert not soft_404("https://ir.test/short", "404 customers added")
    assert not soft_404("https://ir.test/results", "<h1>Results2025</h1><p>404 customers added</p>" * 50, html=True)


def test_dynamic_noise_ignored_business_numbers_preserved():
    a = '<h1>Revenue2025:100million</h1><script>nonce="123";timestamp="today"</script><p nonce="abc">Customers200</p>'
    b = a.replace('123', '999').replace('today', 'tomorrow').replace('abc', 'new')
    assert normalized_digest(a, html=True) == normalized_digest(b, html=True)
    assert normalized_digest(a, html=True) != normalized_digest(a.replace('100million', '101million'), html=True)
    assert normalized_digest(a, html=True) != normalized_digest(a.replace('2025', '2026'), html=True)


def test_daily_quota_counts_attempts_per_tenant(monkeypatch):
    from types import SimpleNamespace

    import pytest

    from app.services import asts_llm_quota, kpi_call_quota

    asts_llm_quota._LOCAL.clear()
    monkeypatch.setenv("KPI_EXTRACTION_CALLS_PER_DAY", "2")
    monkeypatch.setattr(kpi_call_quota, "get_settings", lambda: SimpleNamespace(is_production=False, redis_url=""))
    assert kpi_call_quota.reserve(1)["day_used"] == 1
    assert kpi_call_quota.reserve(1)["day_used"] == 2
    with pytest.raises(kpi_call_quota.KPIDailyDeferred):
        kpi_call_quota.reserve(1)
    assert kpi_call_quota.reserve(2)["day_used"] == 1


def test_normalized_ir_duplicate_skips_parser_and_all_llm(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.models.entities import Base, Company, Document
    from app.services.document_ingestion_service import DocumentIngestionService

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    content = b'<h1>Business results</h1><p>Revenue100million and subscribers200.</p><script>nonce=one</script>'
    with Session(engine) as db:
        db.info["tenant_id"] = "test"
        company = Company(ticker="TEST", name="Test", exchange="NYSE", currency="USD",
                          company_type="holding", valuation_model="unassigned")
        db.add(company)
        db.flush()
        doc = Document(company_id=company.id, title="Results", source_type="IR", source_url="https://ir.test/results",
                       metadata_={"ir_normalized_digest": normalized_digest(content, html=True)})
        db.add(doc)
        db.flush()
        service = DocumentIngestionService()
        monkeypatch.setattr(service, "_parse", lambda *a: (_ for _ in ()).throw(AssertionError("parser called")))
        result = service.ingest_bytes(db, ticker="TEST", title="Results", content=content.replace(b'one', b'two'),
            filename="results.html", source_type="IR", source_url=doc.source_url, content_type="text/html")
        assert result["status"] == "duplicate" and result["document_id"] == doc.id


def test_ir_soft404_never_reaches_parser(monkeypatch):
    from types import SimpleNamespace

    from app.services import document_ingestion_service as ingestion
    service = ingestion.DocumentIngestionService()
    monkeypatch.setattr(ingestion, "resolve_company", lambda *a: SimpleNamespace(id=1))
    result = service.ingest_bytes(None, ticker="TEST", title="error", content=b'<title>Page not found</title>',
        filename="error.html", source_type="IR", source_url="https://ir.test/any", content_type="text/html")
    assert result == {"status": "skipped", "reason": "ir_soft_404", "ticker": "TEST"}
