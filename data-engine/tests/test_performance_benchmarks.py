"""Performance benchmarks test suite for GerarAI.

Fulfills: VAL-COV-005 (add-performance-benchmarks)
- Benchmark: dashboard load time < 500ms
- Benchmark: portfolio valuation calculation < 200ms
- Benchmark: 50-transaction import < 2 seconds
- Regression guard: execution times strictly bounded
"""

from __future__ import annotations

import statistics
import time
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, Portfolio, Position, Transaction
from app.services.cached_portfolio_valuation import (
    CachedPortfolioValuationService,
)
from app.services.portfolio_ledger_service import PortfolioLedgerService
from app.services.transaction_import_service import (
    TransactionImportService,
)


@pytest.fixture
def perf_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "perf-tenant"
        yield session


def _seed_portfolio_with_holdings(db: Session, n_companies: int = 10) -> tuple[Portfolio, list[Company]]:
    port = Portfolio(name="Benchmark Portfolio", base_currency="EUR", is_default=True)
    db.add(port)
    db.commit()
    db.refresh(port)

    companies = []
    for i in range(n_companies):
        c = Company(
            ticker=f"TICK{i:02d}",
            name=f"Benchmark Company {i}",
            exchange="BME",
            currency="EUR",
            sector="Technology",
            industry="Software",
            company_type="operating",
            valuation_model="dcf",
            special_sources=[],
            special_risks=[],
            factor_tags=[],
            domicile_country="ES",
        )
        db.add(c)
        companies.append(c)
    db.commit()
    for c in companies:
        db.refresh(c)

    # Add 5 transactions per company (50 total)
    for c in companies:
        for d in range(1, 6):
            db.add(
                Transaction(
                    company_id=c.id,
                    trade_date=date(2026, 1, d * 5),
                    action="buy",
                    quantity=Decimal("10"),
                    price=Decimal("25.50"),
                    fees=Decimal("1.50"),
                    currency="EUR",
                )
            )
    db.commit()
    return port, companies


def test_benchmark_portfolio_valuation_calculation(perf_db: Session):
    """Cold position creation stays below 200 ms, median of five equal fixtures.

    Each savepoint starts with the seeded transactions and no positions. Rollback
    is outside the timing, so later samples do not silently measure updates to
    positions created by the first sample. Median limits one-off runner jitter;
    the 200 ms threshold is unchanged and every sample remains visible on failure.
    """
    port, companies = _seed_portfolio_with_holdings(perf_db, n_companies=10)
    service = PortfolioLedgerService()

    samples_ms = []
    for _ in range(5):
        assert perf_db.scalar(select(func.count()).select_from(Position)) == 0
        savepoint = perf_db.begin_nested()
        start_time = time.perf_counter()
        for c in companies:
            pos = service.rebuild_position(perf_db, c.id)
            assert pos is not None
        samples_ms.append((time.perf_counter() - start_time) * 1000)
        savepoint.rollback()
        perf_db.expire_all()
    duration_ms = statistics.median(samples_ms)

    # Must complete well below 200ms benchmark (median of 5 runs)
    corridas = ", ".join(f"{sample:.0f}" for sample in samples_ms)
    assert duration_ms < 200, (
        f"Portfolio valuation took {duration_ms:.2f}ms median (threshold: 200ms; "
        f"corridas: {corridas})"
    )


def test_benchmark_dashboard_load_time(perf_db: Session):
    """Dashboard snapshot retrieval must complete in < 500ms."""
    _seed_portfolio_with_holdings(perf_db, n_companies=5)
    service = CachedPortfolioValuationService()

    start_time = time.perf_counter()
    snapshot = service.get_portfolio_snapshot(perf_db)
    duration_ms = (time.perf_counter() - start_time) * 1000

    assert snapshot is not None
    assert duration_ms < 500, f"Dashboard load took {duration_ms:.2f}ms (threshold: 500ms)"


def test_benchmark_50_transaction_import_under_2_seconds(perf_db: Session):
    """Importing and validating 50 transactions must complete in < 2 seconds."""
    port = Portfolio(name="Import Port", base_currency="EUR", is_default=True)
    perf_db.add(port)
    perf_db.commit()
    perf_db.refresh(port)

    # Generate CSV with 50 rows
    lines = ["Fecha Operacion,Ticker,Tipo,Cantidad,Precio,Comision,Divisa"]
    for i in range(1, 51):
        lines.append(f"2026-03-{i % 28 + 1:02d},TEST{i % 5:02d},COMPRA,10,50.00,1.00,EUR")
    csv_bytes = "\n".join(lines).encode("utf-8")

    importer = TransactionImportService()
    start_time = time.perf_counter()
    preview = importer.preview_import(csv_bytes, "transacciones.csv")
    duration_s = time.perf_counter() - start_time

    assert preview.total_rows == 50
    assert preview.valid_rows_count == 50
    assert duration_s < 2.0, f"50-transaction import took {duration_s:.3f}s (threshold: 2.0s)"
