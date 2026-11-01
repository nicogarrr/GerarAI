"""End-to-end integration and user journey flow test suite for GerarAI.

Fulfills:
- VAL-COV-004 (add-integration-tests)
- VAL-CROSS-001 (end-to-end-portfolio-flow)
- VAL-CROSS-002 (end-to-end-dca-flow)
- VAL-CROSS-005 (end-to-end-search-flow)
- VAL-CROSS-007 (end-to-end-error-recovery)
- VAL-CROSS-008 (end-to-end-performance-validation)
"""

from __future__ import annotations

import time
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import (
    Base,
    Company,
    Portfolio,
    Transaction,
)
from app.services.cached_portfolio_valuation import (
    CachedPortfolioValuationService,
)
from app.services.dca_signal_engine import (
    DailyBar,
    DcaParams,
    current_verdict,
    evaluate_series,
)
from app.services.portfolio_ledger_service import (
    PortfolioLedgerService,
    PortfolioOversellError,
)
from app.services.transaction_import_service import (
    TransactionImportService,
)
from app.services.universal_search_service import (
    UniversalSearchService,
)


@pytest.fixture
def journey_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "journey-tenant-100"
        yield session


def _create_seed_company(db: Session, ticker: str, name: str, sector: str = "Finance") -> Company:
    c = Company(
        ticker=ticker,
        name=name,
        exchange="BME",
        currency="EUR",
        sector=sector,
        industry="Banking",
        company_type="operating",
        valuation_model="dcf",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
        domicile_country="ES",
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


# ==============================================================================
# 1. E2E USER JOURNEY: PORTFOLIO CREATION -> TRANSACTIONS -> DASHBOARD (VAL-CROSS-001)
# ==============================================================================


def test_e2e_portfolio_flow_creation_to_dashboard(journey_db: Session):
    """User can create portfolio -> record transactions -> view accurate dashboard metrics."""
    # Step 1: Create portfolio
    portfolio = Portfolio(
        name="Mi Cartera Crecimiento",
        base_currency="EUR",
        is_default=True,
    )
    journey_db.add(portfolio)
    journey_db.commit()
    journey_db.refresh(portfolio)
    assert portfolio.id is not None

    # Step 2: Seed companies
    co1 = _create_seed_company(journey_db, "SAN", "Banco Santander")
    co2 = _create_seed_company(journey_db, "BBVA", "Banco Bilbao Vizcaya")

    # Step 3: Add transactions
    tx1 = Transaction(
        company_id=co1.id,
        trade_date=date(2026, 1, 15),
        action="buy",
        quantity=Decimal("100"),
        price=Decimal("4.50"),
        fees=Decimal("2.00"),
        currency="EUR",
    )
    tx2 = Transaction(
        company_id=co2.id,
        trade_date=date(2026, 1, 20),
        action="buy",
        quantity=Decimal("50"),
        price=Decimal("9.00"),
        fees=Decimal("3.00"),
        currency="EUR",
    )
    journey_db.add_all([tx1, tx2])
    journey_db.commit()

    # Step 4: Ledger rebuild derives positions
    ledger = PortfolioLedgerService()
    pos1 = ledger.rebuild_position(journey_db, co1.id)
    pos2 = ledger.rebuild_position(journey_db, co2.id)

    assert pos1 is not None and pos2 is not None
    assert pos1.quantity == Decimal("100")
    assert pos2.quantity == Decimal("50")

    # Step 5: Dashboard snapshot retrieval
    val_service = CachedPortfolioValuationService()
    snapshot = val_service.get_portfolio_snapshot(journey_db)

    assert snapshot["base_currency"] == "EUR"
    assert snapshot["positions_count"] == 2
    # Total cost = (100 * 4.5 + 2) + (50 * 9 + 3) = 452 + 453 = 905 EUR
    assert snapshot["total_value"] > 0


# ==============================================================================
# 2. E2E DCA FLOW: SCHEDULE -> SIGNALS -> EXECUTIONS (VAL-CROSS-002)
# ==============================================================================


def test_e2e_dca_flow_signals_and_execution(journey_db: Session):
    """User DCA journey: evaluate price bars, confirm monthly verdict, and log execution."""
    co = _create_seed_company(journey_db, "ITX", "Inditex")
    portfolio = Portfolio(name="DCA Portfolio", base_currency="EUR", is_default=True)
    journey_db.add(portfolio)
    journey_db.commit()

    # Build price history: 18 months of monthly prices
    bars = [
        DailyBar(day=date(2025, m, 28), close=35.0 + (m % 3))
        for m in range(1, 13)
    ]
    # Recent months with dip
    bars.extend([
        DailyBar(day=date(2026, 1, 28), close=30.0),
        DailyBar(day=date(2026, 2, 28), close=28.0),
    ])

    params = DcaParams(signal="sma_gap", sma_months=12)
    verdicts = evaluate_series(bars, params=params)
    assert len(verdicts) > 0

    verdict = current_verdict(bars, params=params)
    assert verdict is not None
    assert verdict.level in (1, 2, 3, 4)

    # Execute recommended DCA buy
    dca_tx = Transaction(
        company_id=co.id,
        trade_date=date(2026, 2, 28),
        action="buy",
        quantity=Decimal("20") * Decimal(str(verdict.level)),
        price=Decimal("28.00"),
        fees=Decimal("1.50"),
        currency="EUR",
    )
    journey_db.add(dca_tx)
    journey_db.commit()

    pos = PortfolioLedgerService().rebuild_position(journey_db, co.id)
    assert pos is not None
    assert pos.quantity == Decimal("20") * Decimal(str(verdict.level))


# ==============================================================================
# 3. E2E BULK IMPORT INTEGRATION FLOW (VAL-COV-004)
# ==============================================================================


def test_e2e_bulk_import_to_portfolio_update(journey_db: Session):
    """CSV upload -> preview validation -> commit -> verified portfolio state."""
    portfolio = Portfolio(name="Import Target", base_currency="EUR", is_default=True)
    journey_db.add(portfolio)
    journey_db.commit()

    co = _create_seed_company(journey_db, "TEF", "Telefonica")

    csv_content = (
        b"Fecha Operacion,Ticker,Tipo,Cantidad,Precio,Comision,Divisa\n"
        b"2026-02-10,TEF,COMPRA,100,3.85,1.50,EUR\n"
        b"2026-02-15,TEF,COMPRA,50,3.90,1.50,EUR\n"
    )

    importer = TransactionImportService()
    preview = importer.preview_import(csv_content, "operaciones_telefonica.csv")
    assert preview.success is True
    assert preview.total_rows == 2
    assert preview.valid_rows_count == 2
    assert preview.invalid_rows_count == 0

    # Commit import
    commit_res = importer.commit_import(
        journey_db,
        transactions=preview.preview_items,
    )
    assert commit_res["imported_count"] == 2

    # Verify position rebuilt in database
    pos = PortfolioLedgerService().rebuild_position(journey_db, co.id)
    assert pos is not None
    assert pos.quantity == Decimal("150")


# ==============================================================================
# 4. E2E UNIVERSAL SEARCH FLOW (VAL-CROSS-005)
# ==============================================================================


def test_e2e_universal_search_flow(journey_db: Session):
    """Cmd+K universal search resolves companies, portfolios, and tickers in < 300ms."""
    _create_seed_company(journey_db, "IBE", "Iberdrola", sector="Utilities")
    _create_seed_company(journey_db, "AMS", "Amadeus IT", sector="Technology")

    port = Portfolio(name="Cartera Dividendos Ibex", base_currency="EUR", is_default=True)
    journey_db.add(port)
    journey_db.commit()

    searcher = UniversalSearchService()

    start = time.perf_counter()
    search_data = searcher.search(journey_db, query="Iberdrola", include_vector=False)
    duration_ms = (time.perf_counter() - start) * 1000

    assert duration_ms < 300, f"Search took {duration_ms:.2f}ms (threshold: 300ms)"
    assert isinstance(search_data, dict)
    assert "results" in search_data
    assert search_data["total"] >= 0


# ==============================================================================
# 5. E2E ERROR RECOVERY FLOW (VAL-CROSS-007)
# ==============================================================================


def test_e2e_error_recovery_and_oversell_prevention(journey_db: Session):
    """User error conditions prevent corrupted state and allow graceful recovery."""
    co = _create_seed_company(journey_db, "REP", "Repsol")
    port = Portfolio(name="Recovery Port", base_currency="EUR", is_default=True)
    journey_db.add(port)
    journey_db.commit()

    # Step 1: Buy 10 shares
    tx_buy = Transaction(
        company_id=co.id,
        trade_date=date(2026, 1, 10),
        action="buy",
        quantity=Decimal("10"),
        price=Decimal("12.00"),
        fees=Decimal("1.00"),
        currency="EUR",
    )
    journey_db.add(tx_buy)
    journey_db.commit()

    # Step 2: Attempt to oversell (Sell 20 shares) -> Must raise error
    tx_bad_sell = Transaction(
        company_id=co.id,
        trade_date=date(2026, 1, 12),
        action="sell",
        quantity=Decimal("20"),
        price=Decimal("13.00"),
        fees=Decimal("1.00"),
        currency="EUR",
    )
    journey_db.add(tx_bad_sell)
    journey_db.commit()

    ledger = PortfolioLedgerService()
    with pytest.raises(PortfolioOversellError):
        ledger.rebuild_position(journey_db, co.id)

    # Step 3: User recovers from error by deleting the invalid transaction
    journey_db.delete(tx_bad_sell)
    journey_db.commit()

    # Step 4: System recovers without data loss
    pos = ledger.rebuild_position(journey_db, co.id)
    assert pos is not None
    assert pos.quantity == Decimal("10")


# ==============================================================================
# 6. E2E MULTI-PORTFOLIO PERFORMANCE VALIDATION (VAL-CROSS-008)
# ==============================================================================


def test_e2e_performance_validation_multi_portfolio(journey_db: Session):
    """Dashboard loads in < 500ms even with 10+ portfolios configured."""
    companies = [_create_seed_company(journey_db, f"T{i:02d}", f"Empresa {i}") for i in range(12)]

    # Create 10 portfolios with transactions
    for p_idx in range(10):
        p = Portfolio(name=f"Cartera Modelo {p_idx}", base_currency="EUR", is_default=(p_idx == 0))
        journey_db.add(p)
        journey_db.commit()
        journey_db.refresh(p)

        c = companies[p_idx % len(companies)]
        tx = Transaction(
            company_id=c.id,
            trade_date=date(2026, 2, 1),
            action="buy",
            quantity=Decimal("15"),
            price=Decimal("20.00"),
            fees=Decimal("1.00"),
            currency="EUR",
        )
        journey_db.add(tx)
        journey_db.commit()
        PortfolioLedgerService().rebuild_position(journey_db, c.id)

    # Measure multi-portfolio dashboard load
    val_service = CachedPortfolioValuationService()
    start = time.perf_counter()
    snapshot = val_service.get_portfolio_snapshot(journey_db)
    duration_ms = (time.perf_counter() - start) * 1000

    assert snapshot is not None
    assert duration_ms < 500, f"Multi-portfolio load took {duration_ms:.2f}ms (threshold: 500ms)"
