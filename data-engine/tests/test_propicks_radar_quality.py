"""Overlay de calidad del radar (quality-v1): inputs ausentes nunca pasan."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models import (
    CalculatedMetric,
    Company,
    FinancialFact,
    MarketPrice,
    ProPickCandidate,
    ProPickRun,
    Tenant,
)
from app.services.propicks_radar_quality import quality_for_companies

AS_OF = date(2026, 10, 31)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(engine)()
    session.add(Tenant(id=1, external_id="t"))
    session.commit()
    return session


def _company(db, cid: int, *, sector: str = "Technology", currency: str = "USD") -> Company:
    company = Company(id=cid, ticker=f"Q{cid}", name=f"Quality {cid}", exchange="NASDAQ",
                      currency=currency, sector=sector, industry="Test",
                      company_type="large_cap", valuation_model="dcf")
    db.add(company)
    db.commit()
    return company


def _seed_clear_inputs(db, cid: int) -> None:
    """Todo lo que quality-v1 exige para pasar: embudo, apalancamiento, FCF
    creciente comparable, fundamentales recientes, liquidez y cap>=1B USD."""
    run = ProPickRun(tenant_id=1, as_of=datetime(2026, 10, 30, tzinfo=UTC),
                     status="completed", funnel_version="v1")
    db.add(run)
    db.flush()
    db.add(ProPickCandidate(tenant_id=1, run_id=run.id, company_id=cid, passed=True))
    db.add(CalculatedMetric(tenant_id=1, company_id=cid, metric="net_debt_to_ebitda",
                            value=1.5, period="2025-FY", formula="test"))
    db.add(CalculatedMetric(tenant_id=1, company_id=cid, metric="market_cap",
                            value=2_000_000_000, period="2026-10-30", formula="test"))
    db.add(FinancialFact(tenant_id=1, company_id=cid, metric="free_cash_flow",
                         value=120, unit="USD", period="2025-FY", fiscal_year=2025,
                         filed=AS_OF - timedelta(days=15)))
    db.add(FinancialFact(tenant_id=1, company_id=cid, metric="free_cash_flow",
                         value=100, unit="USD", period="2024-FY", fiscal_year=2024,
                         filed=date(2025, 3, 1)))
    day = AS_OF - timedelta(days=1)
    for i in range(20):
        db.add(MarketPrice(company_id=cid, date=day - timedelta(days=i), open=100, high=100,
                           low=100, close=100, adj_close=100, volume=200_000,
                           quote_currency="USD", source="test"))
    db.commit()


def test_full_inputs_pass(db):
    _company(db, 1)
    _seed_clear_inputs(db, 1)
    verdict = quality_for_companies(db, [1], as_of=AS_OF)[1]
    assert verdict["passed"] is True
    assert verdict["reasons"] == []
    assert verdict["market_cap_usd"] == 2_000_000_000


def test_missing_inputs_never_pass(db):
    _company(db, 2)
    verdict = quality_for_companies(db, [2], as_of=AS_OF)[2]
    assert verdict["passed"] is False
    assert "quality_funnel_not_passed" in verdict["reasons"]
    assert "leverage_missing_or_high" in verdict["reasons"]
    assert "fcf_not_positive_and_growing" in verdict["reasons"]
    assert "fundamentals_stale_or_missing" in verdict["reasons"]
    assert "liquidity_missing_or_low" in verdict["reasons"]
    assert "market_cap_missing_or_low" in verdict["reasons"]


def test_financial_sector_needs_own_model(db):
    _company(db, 3, sector="Financial Services")
    _seed_clear_inputs(db, 3)
    verdict = quality_for_companies(db, [3], as_of=AS_OF)[3]
    assert verdict["passed"] is False
    assert "sector_model_required" in verdict["reasons"]


def test_fcf_not_growing_fails(db):
    _company(db, 4)
    _seed_clear_inputs(db, 4)
    fact = db.query(FinancialFact).filter_by(company_id=4, fiscal_year=2025).one()
    fact.value = 90  # cae respecto a 2024 (100)
    db.commit()
    verdict = quality_for_companies(db, [4], as_of=AS_OF)[4]
    assert "fcf_not_positive_and_growing" in verdict["reasons"]


def test_fcf_non_consecutive_years_not_comparable(db):
    _company(db, 5)
    _seed_clear_inputs(db, 5)
    fact = db.query(FinancialFact).filter_by(company_id=5, fiscal_year=2024).one()
    fact.fiscal_year = 2022  # salto de años: periodos no comparables
    db.commit()
    verdict = quality_for_companies(db, [5], as_of=AS_OF)[5]
    assert "fcf_periods_not_comparable" in verdict["reasons"]


def test_stale_fundamentals_fail(db):
    _company(db, 6)
    _seed_clear_inputs(db, 6)
    for fact in db.query(FinancialFact).filter_by(company_id=6).all():
        fact.filed = AS_OF - timedelta(days=200)
    db.commit()
    verdict = quality_for_companies(db, [6], as_of=AS_OF)[6]
    assert "fundamentals_stale_or_missing" in verdict["reasons"]


def test_non_usd_market_cap_declared_missing(db):
    _company(db, 7, currency="EUR")
    _seed_clear_inputs(db, 7)
    verdict = quality_for_companies(db, [7], as_of=AS_OF)[7]
    assert verdict["market_cap_usd"] is None
    assert "market_cap_missing_or_low" in verdict["reasons"]


def test_few_sessions_fail_liquidity(db):
    _company(db, 8)
    _seed_clear_inputs(db, 8)
    db.query(MarketPrice).filter_by(company_id=8).delete()
    db.add(MarketPrice(company_id=8, date=AS_OF - timedelta(days=1), open=100, high=100,
                       low=100, close=100, adj_close=100, volume=200_000,
                       quote_currency="USD", source="test"))
    db.commit()
    verdict = quality_for_companies(db, [8], as_of=AS_OF)[8]
    assert "liquidity_missing_or_low" in verdict["reasons"]


def test_mixed_quarters_not_paired_as_fiscal_years(db):
    """Un Q3 con fiscal_year relleno NO es un FY: sin filtro, el par
    'dos ultimos FY' podia ser Q3-2026 + FY-2025 y pasar por comparable."""
    _company(db, 9)
    _seed_clear_inputs(db, 9)
    # Deja un solo FY y anade un Q3 del ano siguiente con FCF mayor.
    fact = db.query(FinancialFact).filter_by(company_id=9, fiscal_year=2024).one()
    fact.fiscal_year = 2026
    fact.fiscal_quarter = "Q3"
    fact.period = "2026-Q3"
    fact.value = 500  # "creceria" si se emparejara con FY2025
    db.commit()
    verdict = quality_for_companies(db, [9], as_of=AS_OF)[9]
    assert "fcf_not_positive_and_growing" in verdict["reasons"]


def test_liquidity_dedupes_same_session_rows():
    """Dos filas de la MISMA sesion cuentan UNA. La restriccion
    UNIQUE(company_id, date) de market_prices (0001) ya impide duplicados
    en BD hoy; el dedupe es defensa explicita: si una fuente futura o un
    esquema distinto trajera 2 filas por fecha, el contador no se infla."""
    from app.services.propicks_radar_quality import _liquidity

    class _Result:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

    class _Db:
        def __init__(self, rows):
            self._rows = rows

        def execute(self, _stmt):
            return _Result(self._rows)

    day = date(2026, 10, 30)
    # 10 fechas x 2 proveedores = 20 filas -> 10 sesiones.
    rows = [(1, day - timedelta(days=i), 100, 200_000)
            for i in range(10) for _ in range(2)]
    median_dollars, sessions = _liquidity(_Db(rows), [1])[1]
    assert sessions == 10
    assert median_dollars == 100 * 200_000
    # 20 fechas distintas x 2 proveedores -> 20 sesiones (suficiente).
    rows20 = [(1, day - timedelta(days=i), 100, 200_000)
              for i in range(20) for _ in range(2)]
    _, sessions20 = _liquidity(_Db(rows20), [1])[1]
    assert sessions20 == 20
