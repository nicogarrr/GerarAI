"""Regresión de rendimiento backend: presupuestos de queries, tiempos y paginación.

Herméticos: sqlite propio en tmp_path, sin red, sin LLM, sin tocar la DB docker
ni los puertos 3000/8000. Semilla moderada para que la suite siga rápida.

Run from data-engine/:
    pytest tests/test_performance_regression.py -v
"""

from __future__ import annotations

import time
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401  (registra todas las tablas en Base.metadata)
from app.core.database import Base
from app.models import (
    CashBalance,
    Company,
    FinancialFact,
    FundamentalModelVersion,
    FXRate,
    MarketPrice,
    Portfolio,
    Position,
    ThesisChange,
    ThesisVersion,
    Transaction,
    ValuationModel,
)


def _make_company(i: int, currency: str = "USD") -> Company:
    return Company(
        ticker=f"PERF{i:03d}",
        name=f"Perf Company {i}",
        exchange="NASDAQ",
        currency=currency,
        sector="Tech",
        industry="Software",
        company_type="research_candidate",
        valuation_model="unassigned",
        special_sources=[],
        special_risks=[],
        factor_tags=["growth"],
    )


@pytest.fixture(scope="module")
def perf_db():
    """Motor sqlite aislado con seed determinista (25 compañías).

    Alcance módulo: solo ``test_snapshot_capture_under_2s`` escribe (upsert
    por fecha, re-ejecutable); el resto solo lee. Así la suite no reconstruye
    el seed en cada test.
    """
    import shutil
    import tempfile

    tmpdir = tempfile.mkdtemp(prefix="cavaai_perf_")
    url = f"sqlite:///{Path(tmpdir, 'perf.db').as_posix()}"
    engine = create_engine(url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    today = date.today()
    port = Portfolio(name="Main", base_currency="EUR", is_default=True)
    db.add(port)
    db.flush()
    db.add_all(
        [
            FXRate(
                base_currency="EUR",
                quote_currency="USD",
                rate=Decimal("0.92"),
                rate_date=today - timedelta(days=1),
                source="seed",
            ),
            FXRate(
                base_currency="EUR",
                quote_currency="GBP",
                rate=Decimal("1.17"),
                rate_date=today - timedelta(days=1),
                source="seed",
            ),
            # Par solo inverso: EUR/GBP existe pero USD/GBP no -> ejerce 1/x.
            FXRate(
                base_currency="USD",
                quote_currency="JPY",
                rate=Decimal("150"),
                rate_date=today - timedelta(days=1),
                source="seed",
            ),
        ]
    )
    companies: list[Company] = []
    for i in range(25):
        currency = "USD" if i % 2 else "GBP"
        company = _make_company(i, currency)
        db.add(company)
        companies.append(company)
    db.flush()
    for i, company in enumerate(companies):
        db.add(
            Position(
                portfolio_id=port.id,
                company_id=company.id,
                quantity=Decimal(10 + i),
                average_cost=Decimal(100),
                market_price=Decimal(110 + i),
                market_value=Decimal((10 + i) * (110 + i)),
                unrealized_pnl=Decimal(10 * (10 + i)),
                realized_pnl=Decimal(0),
                currency=company.currency,
                base_currency="EUR",
                market_value_native=Decimal((10 + i) * (110 + i)),
                market_value_base=Decimal((10 + i) * (110 + i)) * Decimal("0.92"),
                cost_basis_native=Decimal((10 + i) * 100),
                cost_basis_base=Decimal((10 + i) * 100) * Decimal("0.92"),
                unrealized_pnl_base=Decimal(10 * (10 + i)),
                realized_pnl_base=Decimal(10 * (10 + i)),
                fx_rate=Decimal("0.92"),
                source="seed",
                as_of=today,
            )
        )
        db.add(
            Transaction(
                portfolio_id=port.id,
                company_id=company.id,
                trade_date=today - timedelta(days=400),
                action="buy",
                quantity=Decimal(10 + i),
                price=Decimal(100),
                fees=Decimal(1),
                currency=company.currency,
                raw_payload={},
            )
        )
        for day_offset in range(20):
            day = today - timedelta(days=20 - day_offset)
            price = Decimal(100 + i + day_offset * 0.1)
            db.add(
                MarketPrice(
                    company_id=company.id,
                    date=day,
                    open=price,
                    high=price,
                    low=price,
                    close=price,
                    adj_close=price,
                    volume=1000,
                    source="seed",
                )
            )
        db.add(
            FinancialFact(
                company_id=company.id,
                metric="eps",
                value=Decimal(5 + i * 0.1),
                unit="USD",
                period="FY",
                fiscal_year=2024,
                source_type="seed",
            )
        )
        db.add(
            ThesisVersion(
                company_id=company.id,
                version=1,
                status="published",
                thesis_markdown="tesis",
                executive_summary="resumen",
                rating="buy",
            )
        )
        db.add(
            FundamentalModelVersion(
                company_id=company.id,
                version=1,
                engine_version="e1",
                algorithm_version="a1",
                framework_key="k",
                horizon_years=5,
                status="ok",
                publishable=True,
                input_fingerprint=f"fp{i}",
                forecast_fingerprint=f"fc{i}",
                market_snapshot_fingerprint=f"ms{i}",
                valuation_snapshot_fingerprint=f"vs{i}",
            )
        )
        db.add(ValuationModel(company_id=company.id, version=1, model_type="dcf", status="ok"))
        db.add(ThesisChange(company_id=company.id, change_type="update", summary="s"))
    db.add(
        CashBalance(
            currency="USD",
            balance=Decimal(10000),
            settled_cash=Decimal(10000),
            interest_rate=Decimal(0),
            source="seed",
            as_of=today,
        )
    )
    db.commit()

    counter = {"n": 0}

    @event.listens_for(engine, "before_cursor_execute")
    def _count(conn, cursor, statement, parameters, context, executemany):
        counter["n"] += 1

    yield db, counter, today
    db.close()
    engine.dispose()
    shutil.rmtree(tmpdir, ignore_errors=True)


def _reset(counter: dict) -> None:
    counter["n"] = 0


def test_snapshot_capture_under_2s(perf_db) -> None:
    """El builder de snapshot con seed debe cerrar en <2s en sqlite, sin red."""
    from app.services.portfolio_snapshot_service import PortfolioSnapshotService

    db, _counter, today = perf_db
    started = time.perf_counter()
    snapshot = PortfolioSnapshotService().capture(db, as_of=today, source="perf-test")
    elapsed = time.perf_counter() - started
    assert elapsed < 2.0, f"snapshot.capture tardó {elapsed:.2f}s (>2s)"
    assert snapshot.total_value_base > 0
    assert snapshot.pricing_coverage == Decimal("1")


def test_positions_fiscal_batch_matches_row_by_row(perf_db) -> None:
    from sqlalchemy import desc  # noqa: F401

    from app.api.routes.portfolio import _fiscal_info, _fiscal_info_batch

    db, counter, _today = perf_db
    rows = db.execute(
        select(Position, Company).join(Company, Position.company_id == Company.id)
    ).all()
    expected = {
        company.id: _fiscal_info(db, company.id, position.as_of)
        for position, company in rows
    }
    _reset(counter)
    batch = _fiscal_info_batch(
        db, {company.id: position.as_of for position, company in rows}
    )
    assert counter["n"] == 1, f"fiscal batch debe usar 1 query, usó {counter['n']}"
    assert batch == expected
    assert all(info["fiscal_bucket"] == "largo_plazo" for info in batch.values())


def test_fx_batch_matches_single_rate(perf_db) -> None:
    from app.services.portfolio_fx_service import PortfolioFXService

    db, counter, today = perf_db
    fx = PortfolioFXService()
    old = today - timedelta(days=1)
    # Directo, inverso (JPY solo existe como USD/JPY -> EUR/JPY es 1/x),
    # misma moneda y divisa inexistente.
    cases = [
        ("USD", "EUR", today),
        ("GBP", "EUR", today),
        ("JPY", "EUR", today),
        ("EUR", "EUR", today),
        ("CHF", "EUR", today),
        ("USD", "EUR", old),
    ]
    for quote, base, as_of in cases:
        assert fx.rate(db, quote_currency=quote, base_currency=base, as_of=as_of) == (
            fx.rates_for(
                db, quote_currencies={quote}, base_currency=base, as_of=as_of
            ).get(quote.upper())
        ), f"rates_for diverge de rate() para {quote}/{base}@{as_of}"
    _reset(counter)
    table = fx.fx_table(
        db, currencies={"USD", "GBP", "JPY", "CHF"}, base_currency="EUR", as_of_max=today
    )
    assert counter["n"] == 1
    for quote, base, as_of in cases:
        assert fx.rate(
            db, quote_currency=quote, base_currency=base, as_of=as_of
        ) == PortfolioFXService.rate_from_table(
            table, quote_currency=quote, base_currency=base, as_of=as_of
        ), f"rate_from_table diverge de rate() para {quote}/{base}@{as_of}"


def test_intelligence_query_budget(perf_db) -> None:
    from app.services.portfolio_intelligence_service import PortfolioIntelligenceService

    db, counter, _today = perf_db
    _reset(counter)
    payload = PortfolioIntelligenceService().build(db, years=1)
    # 25 posiciones sin lote = >150 queries; con lote debe caber en ~15.
    assert counter["n"] <= 25, f"intelligence usó {counter['n']} queries (>25)"
    assert payload["coverage"]["positions"] == 25
    assert payload["performance"]["twr"] is not None


def test_company_snapshot_query_budget(perf_db) -> None:
    from app.services.company_snapshot_service import CompanySnapshotService

    db, counter, _today = perf_db
    company = db.scalar(select(Company).where(Company.ticker == "PERF000"))
    assert company is not None
    _reset(counter)
    snapshot = CompanySnapshotService().build(db, company)
    # 4 lecturas + recent_changes + conteos en 1 query + 2 del enriquecimiento
    # por lote (reviews puente + eventos, una cada una, no N+1) = 8.
    assert counter["n"] <= 8, f"company snapshot usó {counter['n']} queries (>8)"
    assert snapshot.counts.facts == 1
    assert snapshot.counts.thesis_versions == 1


def test_risk_dashboard_query_budget(perf_db) -> None:
    from app.services.risk_service import RiskService

    db, counter, _today = perf_db
    _reset(counter)
    result = RiskService().dashboard(db)
    assert counter["n"] <= 6, f"risk dashboard usó {counter['n']} queries (>6)"
    assert result["status"] == "ok"


def test_pagination_caps_are_enforced(perf_db) -> None:
    from app.api.routes import companies as companies_routes
    from app.api.routes import portfolio as portfolio_routes

    db, _counter, _today = perf_db
    # Contrato paginado actual: /transactions/page y sobres items+page_info.
    assert len(portfolio_routes.transactions_page(limit=5, offset=0, db=db)["items"]) == 5
    assert len(portfolio_routes.transactions_page(limit=5, offset=5, db=db)["items"]) == 5
    assert len(portfolio_routes.positions(limit=5, offset=0, db=db)["items"]) == 5
    assert len(portfolio_routes.positions(limit=5, offset=5, db=db)["items"]) == 5
    assert len(portfolio_routes.list_fx_rates(limit=1, offset=0, db=db)["items"]) == 1
    assert len(companies_routes.list_companies(limit=5, offset=0, db=db)) == 5
    assert len(companies_routes.list_companies(limit=5, offset=25, db=db)) == 0
    # Los techos existen en la firma (Query le=...).
    import inspect as _inspect

    for fn, name, ceiling in [
        # /transactions usa page/page_size; el listado limit/offset es /transactions/page.
        (portfolio_routes.transactions_page, "transactions_page", 200),
        (portfolio_routes.positions, "positions", 2000),
        (portfolio_routes.list_fx_rates, "fx-rates", 2000),
        (companies_routes.list_companies, "companies", 500),
    ]:
        params = _inspect.signature(fn).parameters
        assert "limit" in params, f"{name} sin parámetro limit"


def test_perf_indexes_present_in_metadata() -> None:
    expected = {
        "ix_fx_rates_base_quote_date",
        "ix_positions_portfolio_company",
        "ix_transactions_portfolio_trade_date",
        "ix_transactions_company_action",
        "ix_portfolio_snapshots_portfolio_date",
        "ix_documents_company_id",
        "ix_document_chunks_doc_idx",
        "ix_financial_facts_company_metric_year",
        "ix_calculated_metrics_company_metric",
        "ix_valuation_models_company_version",
        "ix_thesis_versions_company_version",
        "ix_claims_company_status",
        "ix_thesis_changes_company_created",
        "ix_thesis_changes_tenant_company_id",
        "ix_research_reviews_company_status",
        "ix_research_alerts_company_status",
    }
    found = {
        index.name
        for table in Base.metadata.tables.values()
        for index in table.indexes
    }
    assert expected.issubset(found), f"faltan índices: {expected - found}"


def test_migration_0021_has_upgrade_and_downgrade() -> None:
    import importlib.util

    path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "0021_perf_hot_path_indexes.py"
    )
    assert path.exists(), "falta la migración 0021"
    spec = importlib.util.spec_from_file_location("m0021", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "0021_perf_hot_path_indexes"
    assert module.down_revision == "0020_news_event_metadata"
    assert callable(module.upgrade) and callable(module.downgrade)
    assert len(module.INDEXES) >= 10


def test_migration_0118_has_upgrade_and_downgrade() -> None:
    """0118: indice compuesto de thesis_changes para /api/attention-thesis.

    MEDIDO por el piloto (EXPLAIN ANALYZE, 2026-10-31, bajo restore+build
    concurrentes): la consulta principal hace 466 sondas por company_id con
    ~64 filas cada una y descarta 29.456 por el filtro id = thesis_change_id
    (18.936 buffer hits). El planner estimaba rows=3 (real: 64) y eligio
    ix_thesis_changes_company_id; con (tenant_id, company_id, id) las tres
    condiciones van al indice y cada sonda toca 1 fila.
    """
    import importlib.util

    path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "0118_thesis_changes_attention_thesis.py"
    )
    assert path.exists(), "falta la migración 0118"
    spec = importlib.util.spec_from_file_location("m0118", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "0118_thesis_changes_attention_thesis"
    assert module.down_revision == "0117_fk_child_indexes"
    assert callable(module.upgrade) and callable(module.downgrade)
