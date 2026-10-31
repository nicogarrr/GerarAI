"""Auditoría backend: crashes y fugas — tests de cada fix.

Un test por fix, en un solo fichero para no tocar los existentes.
"""

from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, Tenant, Transaction


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-audit"
        yield session


def _company(db: Session, ticker: str = "AAPL") -> Company:
    company = Company(
        ticker=ticker, name=f"{ticker} Inc", exchange="NASDAQ", currency="USD",
        sector="Tech", industry="Tech", company_type="standard",
        valuation_model="standard_dcf", special_sources=[], special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


# ---------------------------------------------------------------------------
# (2) sensitivity_grid / reverse_dcf
# ---------------------------------------------------------------------------


def test_sensitivity_grid_rejects_invalid_base():
    from app.valuation.dcf_fcff import DCFInputs
    from app.valuation.sensitivity import sensitivity_grid

    base = DCFInputs(
        revenue=100.0, revenue_growth=0.1, fcf_margin=0.2, wacc=0.05,
        terminal_growth=0.05, net_debt=0.0, shares_outstanding=10.0,
    )
    with pytest.raises(ValueError, match="Sensitivity base inputs are invalid"):
        sensitivity_grid(base, [0.1], [0.08])

    zero_shares = DCFInputs(
        revenue=100.0, revenue_growth=0.1, fcf_margin=0.2, wacc=0.1,
        terminal_growth=0.02, net_debt=0.0, shares_outstanding=0.0,
    )
    with pytest.raises(ValueError, match="Sensitivity base inputs are invalid"):
        sensitivity_grid(zero_shares, [0.1], [0.12])


def test_sensitivity_grid_isolates_failing_cells():
    from app.valuation.dcf_fcff import DCFInputs
    from app.valuation.sensitivity import sensitivity_grid

    base = DCFInputs(
        revenue=100.0, revenue_growth=0.1, fcf_margin=0.2, wacc=0.1,
        terminal_growth=0.02, net_debt=0.0, shares_outstanding=10.0,
    )
    # 0.01 <= terminal_growth rompe solo esa celda; el grid no cae.
    grid = sensitivity_grid(base, [0.1], [0.01, 0.12])
    cells = grid["rows"][0]["values"]
    assert cells[0]["value_per_share"] is None
    assert cells[0]["error"] == "cell_out_of_range"
    assert cells[1]["value_per_share"] is not None
    assert "error" not in cells[1]


def test_reverse_dcf_validates_and_flags_out_of_bounds():
    from app.valuation.reverse_dcf import ReverseDCFInputs, solve_required_growth

    bad = ReverseDCFInputs(
        market_price=50.0, revenue=0.0, fcf_margin=0.2, wacc=0.1,
        terminal_growth=0.02, net_debt=0.0, shares_outstanding=10.0,
    )
    with pytest.raises(ValueError, match="Reverse DCF inputs are invalid"):
        solve_required_growth(bad)

    ok_inputs = ReverseDCFInputs(
        market_price=50.0, revenue=100.0, fcf_margin=0.2, wacc=0.1,
        terminal_growth=0.02, net_debt=0.0, shares_outstanding=10.0,
    )
    in_range = solve_required_growth(ok_inputs)
    assert in_range["out_of_bounds"] is False

    # Precio absurdo por encima del rango valorable -> flag, no crash.
    crazy = ReverseDCFInputs(
        market_price=10**12, revenue=100.0, fcf_margin=0.2, wacc=0.1,
        terminal_growth=0.02, net_debt=0.0, shares_outstanding=10.0,
    )
    out = solve_required_growth(crazy)
    assert out["out_of_bounds"] is True
    assert out["trace"]["out_of_bounds"] is True


# ---------------------------------------------------------------------------
# (3) portfolio_ledger + tax_report
# ---------------------------------------------------------------------------


def test_ledger_rejects_invalid_inputs(db):
    from app.services.portfolio_ledger_service import PortfolioLedgerService

    service = PortfolioLedgerService()
    with pytest.raises(ValueError, match="quantity must be positive"):
        service.create_transaction(
            db, ticker="AAPL", action="buy", quantity=Decimal("0"),
            price=Decimal("10"), trade_date=date(2026, 1, 10),
        )
    with pytest.raises(ValueError, match="cannot be in the future"):
        service.create_transaction(
            db, ticker="AAPL", action="buy", quantity=Decimal("1"),
            price=Decimal("10"), trade_date=date(2999, 1, 1),
        )
    with pytest.raises(ValueError, match="Unsupported ledger action"):
        service.create_transaction(
            db, ticker="AAPL", action="split", quantity=Decimal("1"),
            price=Decimal("10"), trade_date=date(2026, 1, 10),
        )
    with pytest.raises(ValueError, match="cannot be negative"):
        service.create_transaction(
            db, ticker="AAPL", action="buy", quantity=Decimal("1"),
            price=Decimal("-5"), trade_date=date(2026, 1, 10),
        )


def test_ledger_oversell_and_mixed_currency_are_typed(db):
    from app.services.portfolio_ledger_service import (
        PortfolioLedgerService,
        PortfolioMixedCurrencyError,
        PortfolioOversellError,
    )

    service = PortfolioLedgerService()
    service.create_transaction(
        db, ticker="AAPL", action="buy", quantity=Decimal("10"),
        price=Decimal("100"), trade_date=date(2026, 1, 10), currency="EUR",
    )
    with pytest.raises(PortfolioOversellError, match="Cannot sell"):
        service.create_transaction(
            db, ticker="AAPL", action="sell", quantity=Decimal("11"),
            price=Decimal("150"), trade_date=date(2026, 2, 10), currency="EUR",
        )
    with pytest.raises(PortfolioMixedCurrencyError, match="cannot mix transaction currencies"):
        service.create_transaction(
            db, ticker="AAPL", action="buy", quantity=Decimal("1"),
            price=Decimal("100"), trade_date=date(2026, 2, 10), currency="USD",
        )
    # Siguen siendo ValueError (compatibilidad con manejadores genéricos).
    assert issubclass(PortfolioOversellError, ValueError)
    assert issubclass(PortfolioMixedCurrencyError, ValueError)


def test_tax_report_warns_over_sell_instead_of_silent_gain(db):
    from app.services.tax_report_service import TaxReportService

    company = _company(db, "OVS")
    db.add_all(
        [
            Transaction(
                company_id=company.id, trade_date=date(2026, 1, 10), action="buy",
                quantity=Decimal("10"), price=Decimal("100"), fees=Decimal("0"),
                currency="USD", external_id=f"buy-{uuid4().hex}",
            ),
            # Over-sell directo en ledger (más vendido que comprado).
            Transaction(
                company_id=company.id, trade_date=date(2026, 3, 10), action="sell",
                quantity=Decimal("15"), price=Decimal("120"), fees=Decimal("0"),
                currency="USD", external_id=f"sell-{uuid4().hex}",
            ),
        ]
    )
    db.commit()

    report = TaxReportService().compute_report(db, 2026)
    bucket = next(b for b in report["realized"] if b["ticker"] == "OVS")
    assert bucket["over_sell"] is True
    assert bucket["over_sell_count"] == 1
    assert "OVS" in report["summary"]["over_sell"]
    sale = bucket["sales"][0]
    assert sale["over_sell"] is True
    assert sale["over_sell_quantity"] == 5.0
    assert sale["warning"] is not None and "over_sell" in sale["warning"]


def test_tax_report_rejects_non_positive_quantities_in_ingesta(db):
    from app.services.tax_report_service import TaxReportService

    company = _company(db, "ZERO")
    db.add_all(
        [
            # Lote basura con cantidad 0: no entra a la base de coste.
            Transaction(
                company_id=company.id, trade_date=date(2026, 1, 5), action="buy",
                quantity=Decimal("0"), price=Decimal("999"), fees=Decimal("0"),
                currency="USD", external_id=f"zero-{uuid4().hex}",
            ),
            Transaction(
                company_id=company.id, trade_date=date(2026, 1, 10), action="buy",
                quantity=Decimal("10"), price=Decimal("100"), fees=Decimal("0"),
                currency="USD", external_id=f"buy-{uuid4().hex}",
            ),
            Transaction(
                company_id=company.id, trade_date=date(2026, 3, 10), action="sell",
                quantity=Decimal("5"), price=Decimal("150"), fees=Decimal("0"),
                currency="USD", external_id=f"sell-{uuid4().hex}",
            ),
        ]
    )
    db.commit()

    report = TaxReportService().compute_report(db, 2026)
    bucket = next(b for b in report["realized"] if b["ticker"] == "ZERO")
    # Ganancia solo del lote real: 5*150 - 5*100 = 250.
    assert bucket["gain_native"] == 250.0
    assert bucket["over_sell"] is False


# ---------------------------------------------------------------------------
# (4) replay fail-closed + database fail-closed
# ---------------------------------------------------------------------------


def test_replay_fails_closed_without_redis_when_required():
    from app.core.replay import NonceBackendUnavailable, consume_nonce, reset_local_nonces

    reset_local_nonces()
    key = f"audit-{uuid4().hex}"

    async def consume_closed():
        return await consume_nonce(
            key, ttl_seconds=30, redis_url="redis://127.0.0.1:1/0",
            use_redis=True, allow_local_fallback=False,
        )

    with pytest.raises(NonceBackendUnavailable):
        asyncio.run(consume_closed())


def test_replay_keeps_local_fallback_when_allowed():
    from app.core.replay import consume_nonce, reset_local_nonces

    reset_local_nonces()
    key = f"audit-{uuid4().hex}"

    async def consume():
        return await consume_nonce(
            key, ttl_seconds=30, redis_url="redis://127.0.0.1:1/0",
            use_redis=True, allow_local_fallback=True,
        )

    assert asyncio.run(consume()) is True
    assert asyncio.run(consume()) is False


def test_get_db_fails_closed_without_principal_when_auth_required(monkeypatch):
    import app.core.database as database_module

    stub = SimpleNamespace(research_auth_required=True)
    monkeypatch.setattr(database_module, "settings", stub)
    gen = database_module.get_db(principal=None)
    with pytest.raises(HTTPException) as exc_info:
        next(gen)
    assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# rate_limit EXEMPT_PATHS /api/health*
# ---------------------------------------------------------------------------


def test_health_paths_are_exempt():
    from app.core.rate_limit import EXEMPT_PATHS, is_exempt_path

    assert is_exempt_path("/")
    assert is_exempt_path("/health")
    assert is_exempt_path("/health/live")
    assert is_exempt_path("/health/ready")
    assert is_exempt_path("/api/health")
    assert is_exempt_path("/api/health/live")
    assert "/api/health" not in EXEMPT_PATHS  # el prefijo lo cubre el helper
    assert not is_exempt_path("/api/portfolio")
    assert not is_exempt_path("/api/healthchecklist")


# ---------------------------------------------------------------------------
# (1) safe_detail en thesis / work_products / knowledge
# ---------------------------------------------------------------------------


def test_thesis_generate_error_is_fixed_and_opaque():
    from app.api.routes.thesis import _safe_generate_error

    err_404 = _safe_generate_error(ValueError("Unknown ticker: XYZ"))
    assert err_404.status_code == 404
    assert err_404.detail == "Company not found"

    err_400 = _safe_generate_error(ValueError("weird internal state 'XYZ'"))
    assert err_400.status_code == 400
    assert "weird internal state" not in str(err_400.detail)
    assert "ref" in str(err_400.detail)

    err_500 = _safe_generate_error(RuntimeError("boom secret"))
    assert err_500.status_code == 500
    assert "boom secret" not in str(err_500.detail)


def test_knowledge_ref_error_hides_internals():
    from app.api.routes.knowledge import _ref_error

    err = _ref_error(409, "Principle action conflict", ValueError("db exploded"))
    assert err.status_code == 409
    assert "db exploded" not in str(err.detail)
    assert "Principle action conflict" in str(err.detail)


def test_knowledge_upload_whitelist():
    from app.api.routes.knowledge import validate_upload_metadata

    ok = validate_upload_metadata(
        document_type="personal_note", language="en", source_url=None
    )
    assert ok == ("personal_note", "en", None)

    with pytest.raises(ValueError, match="Unsupported knowledge document type"):
        validate_upload_metadata(document_type="tweet", language="en", source_url=None)
    with pytest.raises(ValueError, match="Unsupported knowledge language"):
        validate_upload_metadata(document_type="book", language="xx", source_url=None)
    with pytest.raises(ValueError, match="Invalid knowledge source_url"):
        validate_upload_metadata(
            document_type="book", language="es", source_url="not a url"
        )
    _, _, validated = validate_upload_metadata(
        document_type="book", language="es", source_url="https://example.com/doc.pdf"
    )
    assert validated.startswith("https://")


def test_knowledge_upload_source_url_measured_after_normalization():
    """La normalizacion HttpUrl ALARGA: '/' final (+1) e IDN -> punycode
    (munch: +7). La cota de 1000 (String(1000)) se mide sobre la URL FINAL,
    no sobre la entrada: una entrada de 1000 chars guarda 1001 y rompe PG."""
    from app.api.routes.knowledge import validate_upload_metadata

    # Entrada de exactamente 1000 chars sin '/': normaliza a 1001.
    edge_slash = "https://example.com" + "a" * 981
    assert len(edge_slash) == 1000
    with pytest.raises(ValueError, match="Invalid knowledge source_url"):
        validate_upload_metadata(document_type="book", language="en", source_url=edge_slash)

    # IDN: 995 chars de entrada, punycode la deja en 1002.
    edge_idn = "https://m\u00fcnchen.example/" + "a" * 971
    assert len(edge_idn) == 995
    with pytest.raises(ValueError, match="Invalid knowledge source_url"):
        validate_upload_metadata(document_type="book", language="en", source_url=edge_idn)

    # Control: 1000 chars ya normalizada (con '/') sigue aceptandose.
    ok_url = "https://example.com/" + "a" * 980
    assert len(ok_url) == 1000
    _, _, validated = validate_upload_metadata(
        document_type="book", language="en", source_url=ok_url
    )
    assert len(validated) == 1000


def test_knowledge_upload_source_url_capped_at_column_length():
    """KnowledgeDocument.source_url es String(1000): una URL valida pero mas
    larga debe rechazarse en la whitelist (400), no romper el INSERT en
    Postgres. HttpUrl solo corta en 2083, asi que hace falta tope propio."""
    from app.api.routes.knowledge import validate_upload_metadata

    long_url = "https://example.com/" + "a" * 1200  # 1220 chars: HttpUrl la acepta
    with pytest.raises(ValueError, match="Invalid knowledge source_url"):
        validate_upload_metadata(document_type="book", language="en", source_url=long_url)


# ---------------------------------------------------------------------------
# memory.py enums cerrados
# ---------------------------------------------------------------------------


def test_memory_enums_reject_open_strings():
    from fastapi import HTTPException as FastAPIHTTPException

    from app.api.routes.memory import validate_memory_item_enums

    validate_memory_item_enums(
        scope="portfolio", memory_type="note", status="active", source_type="user"
    )
    with pytest.raises(FastAPIHTTPException) as exc_info:
        validate_memory_item_enums(
            scope="global", memory_type="note", status="active", source_type="user"
        )
    assert exc_info.value.status_code == 400
    with pytest.raises(HTTPException):
        validate_memory_item_enums(
            scope="portfolio", memory_type="freeform-junk", status="active",
            source_type="user",
        )


# ---------------------------------------------------------------------------
# export.py: None≠0, as_of opcional, escape CSV
# ---------------------------------------------------------------------------


def test_export_none_is_not_zero_and_csv_escapes_formulas():
    from app.api.routes.export import _csv_cell, _num

    assert _num(None) is None
    assert _num(0) == 0.0
    assert _csv_cell("=HYPERLINK('x')") == "'=HYPERLINK('x')"
    assert _csv_cell("+123") == "'+123"
    assert _csv_cell("-5") == "'-5"
    assert _csv_cell("@user") == "'@user"
    assert _csv_cell("|cmd") == "'|cmd"
    assert _csv_cell("%x") == "'%x"
    assert _csv_cell("AAPL") == "AAPL"
    assert _csv_cell(12.5) == 12.5
    assert _csv_cell(None) is None


# ---------------------------------------------------------------------------
# settings.py: qdrant bool + MAF dinámica
# ---------------------------------------------------------------------------


def test_settings_contract_is_opaque():
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    import main
    from app.core.database import get_db
    from app.models.entities import Base

    # StaticPool: el TestClient sirve en otro hilo; la memoria debe compartirse.
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = factory()

    def _override():
        yield session

    main.app.dependency_overrides[get_db] = _override
    try:
        client = TestClient(main.app)
        response = client.get("/api/settings")
    finally:
        main.app.dependency_overrides.clear()
        session.close()
        engine.dispose()
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload["connectors"]["qdrant_url"], bool)
    assert str(payload["maf_version"]).startswith("agent-framework-core==")


# ---------------------------------------------------------------------------
# chat_service: índice por ticker + regex de palabra
# ---------------------------------------------------------------------------


def test_chat_resolve_company_avoids_substring_false_positive(db):
    from app.services.chat_service import ChatService

    _company(db, "IT")
    service = ChatService.__new__(ChatService)  # sin provider LLM
    # "IT" aparece dentro de "WITH" pero no es mención del ticker.
    assert service._resolve_company(db, "WITH strong moat", "company", None) is None
    # Mención real sí resuelve.
    found = service._resolve_company(db, "What about IT stock?", "company", None)
    assert found is not None and found.ticker == "IT"


# ---------------------------------------------------------------------------
# llm_router: sin tabla premium ficticia
# ---------------------------------------------------------------------------


def test_no_premium_route_in_contract():
    from app.services.llm_router import ROUTES, route_model, route_table

    # La ruta premium existe como alias eval-gated, pero apunta al modelo Go
    # aprobado por el dueno: ningun modelo premium ficticio ni de pago.
    assert ROUTES["premium_financial_analysis"].model == "deepseek-v4.1-flash"
    assert route_model("premium_financial_analysis").model == "deepseek-v4.1-flash"
    premium_rows = [row for row in route_table() if row["task"].startswith("premium_")]
    assert premium_rows and all(row["model"] == "deepseek-v4.1-flash" for row in premium_rows)


# ---------------------------------------------------------------------------
# universal_search: modo real
# ---------------------------------------------------------------------------


def test_universal_search_labels_lexical_only_without_vector(db):

    from app.models.entities import Document, DocumentChunk
    from app.services.universal_search_service import UniversalSearchService

    tenant = Tenant(external_id="audit-search", name="audit")
    db.add(tenant)
    db.flush()
    db.info["tenant_id"] = tenant.id
    company = Company(
        ticker="SRCH", name="Search Co", exchange="TEST", currency="USD",
        sector="Industrials", industry="Test", company_type="standard",
        valuation_model="standard_dcf", special_sources=[], special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.flush()
    filing = Document(
        company_id=company.id, title="annual filing",
        source_type="sec_filing", source_url="https://www.sec.gov/example",
    )
    db.add(filing)
    db.flush()
    db.add(
        DocumentChunk(
            document_id=filing.id, chunk_index=0,
            text="Capital allocation discipline prioritized reinvestment.",
        )
    )
    db.commit()

    response = UniversalSearchService().search(db, "reinvestment")
    assert response["retrieval"]["mode"] == "lexical_only"
    assert response["total"] >= 1

    not_found = UniversalSearchService().search(db, "reinvestment", ticker="NOPE")
    assert not_found["retrieval"]["mode"] == "lexical_only"


# ---------------------------------------------------------------------------
# workers: idempotencia + lease TTL
# ---------------------------------------------------------------------------


def test_emit_fingerprint_is_stable():
    from app.workers.dramatiq_app import _emit_fingerprint

    assert _emit_fingerprint("a", "b") == _emit_fingerprint("a", "b")
    assert _emit_fingerprint("a", "b") != _emit_fingerprint("a", "c")


def test_job_lease_blocks_second_holder_until_release_or_expiry():
    from app.workers.dramatiq_app import (
        acquire_job_lease,
        release_job_lease,
        reset_local_leases,
    )

    reset_local_leases()
    token = acquire_job_lease("audit-job", ttl_seconds=60, redis_url=None)
    assert token is not None
    assert acquire_job_lease("audit-job", ttl_seconds=60, redis_url=None) is None
    release_job_lease("audit-job", token, redis_url=None)
    assert acquire_job_lease("audit-job", ttl_seconds=60, redis_url=None) is not None
    reset_local_leases()


# ---------------------------------------------------------------------------
# thesis_service: savepoint en vez de rollback global
# ---------------------------------------------------------------------------


def test_thesis_generate_rolls_back_savepoint_not_session(monkeypatch):
    from app.services.thesis_service import ThesisService

    service = ThesisService()
    db = MagicMock()
    savepoint = MagicMock()

    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(service, "_generate_atomic", _boom)
    db.begin_nested.return_value = savepoint
    with pytest.raises(RuntimeError, match="boom"):
        service.generate(db, "AAPL")
    savepoint.rollback.assert_called_once_with()
    db.rollback.assert_not_called()


# ---------------------------------------------------------------------------
# insider: parse-errors en provenance + caché por accession
# ---------------------------------------------------------------------------


def test_insider_counts_parse_errors_in_provenance(monkeypatch):
    from app.services import insider_service
    from app.services.connectors import form4 as form4_connector

    insider_service.clear_filing_xml_cache()
    filings = [
        {
            "form": "4", "accession_number": "0001", "filing_date": "2026-01-01",
            "document_url": "https://www.sec.gov/Archives/x/0001/doc.xml",
        }
    ]
    monkeypatch.setattr(
        form4_connector, "recent_form4_filings", lambda *a, **k: filings
    )
    monkeypatch.setattr(
        insider_service, "_cik_for_ticker", lambda ticker, client=None: "0000000001"
    )

    def _broken(filing):
        raise ValueError("bad xml")

    result = insider_service.get_signals_for_ticker("AAPL", fetcher=_broken)
    # Every filing failed to parse. Reporting "ok" with an empty signal list
    # reads as "no insider activity", which is a false all-clear on the exact
    # case where nothing could be read.
    assert result["status"] == "degraded"
    assert result["filings_parsed"] == 0
    assert result["filings_failed"] == 1
    assert result["coverage_ratio"] == 0.0
    assert result["provenance"]["coverage"] == "partial"
    assert result["parse_error_count"] == 1
    assert "1 filing(s) con error" in result["provenance"]["note"]
    assert result["provenance"]["coverage"] == "partial"


def test_insider_filing_xml_cached_per_accession(monkeypatch):
    from app.services import insider_service

    insider_service.clear_filing_xml_cache()
    calls: list[str] = []

    class _FakeResponse:
        text = "<ownershipDocument></ownershipDocument>"

        def raise_for_status(self):
            return None

    class _FakeClient:
        def get(self, url, headers=None):
            calls.append(url)
            return _FakeResponse()

    filing = {
        "accession_number": "ACC-1",
        "document_url": "https://www.sec.gov/Archives/x/ACC-1/doc.xml",
    }
    client = _FakeClient()
    xml1, _ = insider_service._cached_filing_xml(filing, client=client)
    xml2, _ = insider_service._cached_filing_xml(filing, client=client)
    assert xml1 == xml2
    assert len(calls) == 1  # segunda lectura sale de la caché TTL


# ---------------------------------------------------------------------------
# market_refresh: semáforo + timeout por ticker
# ---------------------------------------------------------------------------


def test_market_refresh_bounds_concurrency_and_times_out():
    import asyncio as _asyncio

    from app.services.market_refresh_service import PublicPriceProvider

    in_flight = 0
    peak = 0

    async def _slow_one(company, as_of):
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        try:
            await _asyncio.sleep(0.05)
            return company, None, {"ticker": company.ticker, "reason": "x"}
        finally:
            in_flight -= 1

    provider = PublicPriceProvider.__new__(PublicPriceProvider)
    provider._one = _slow_one  # type: ignore[method-assign]
    companies = [SimpleNamespace(ticker=f"T{i}") for i in range(12)]
    observations, errors = _asyncio.run(
        provider.fetch(companies, as_of=date(2026, 9, 1))
    )
    assert observations == {}
    assert len(errors) == 12
    assert peak <= PublicPriceProvider.MAX_IN_FLIGHT
    assert 5 <= PublicPriceProvider.MAX_IN_FLIGHT <= 8


def test_market_refresh_per_ticker_timeout(monkeypatch):
    import asyncio as _asyncio

    from app.services.market_refresh_service import PublicPriceProvider

    async def _hang(company, as_of):
        await _asyncio.sleep(5)
        return company, None, None  # pragma: no cover

    monkeypatch.setattr(
        PublicPriceProvider, "PER_TICKER_TIMEOUT_SECONDS", 0.01
    )
    provider = PublicPriceProvider.__new__(PublicPriceProvider)
    provider._one = _hang  # type: ignore[method-assign]
    observations, errors = _asyncio.run(
        provider.fetch([SimpleNamespace(ticker="SLOW")], as_of=date(2026, 9, 1))
    )
    assert observations == {}
    assert errors == [{"ticker": "SLOW", "reason": "per_ticker_timeout"}]


# ---------------------------------------------------------------------------
# public_fetch: content-length con try/default
# ---------------------------------------------------------------------------


def test_parse_content_length_never_raises():
    from app.services.public_fetch import _parse_content_length

    assert _parse_content_length(None) is None
    assert _parse_content_length("garbage") is None
    assert _parse_content_length("") is None
    assert _parse_content_length("-5") is None
    assert _parse_content_length("123") == 123
