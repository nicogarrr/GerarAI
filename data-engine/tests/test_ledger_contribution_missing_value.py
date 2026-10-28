"""Sin valor de mercado en divisa base no hay contribucion inventada (N/D)."""

from datetime import date, timedelta

from app.services.portfolio_intelligence_service import PortfolioIntelligenceService
from tests.test_ledger_contribution import (  # noqa: F401  (fixture db)
    CUTOFF,
    _company,
    _position,
    _price,
    _tx,
    _usd_base,
    db,
)


def _entry(db, *, with_ledger_gap: bool):
    _usd_base(db)
    company = _company(db)
    position = _position(db, company, qty=10, price=150)
    position.market_value_base = None  # sin FX/precio: N/D
    db.commit()
    _tx(db, company, "buy", 10, 100, date(2025, 6, 1))
    _price(db, company, CUTOFF - timedelta(days=1), 120)
    if with_ledger_gap:
        position.quantity = 12
        db.commit()
    result = PortfolioIntelligenceService()._ledger_contribution(db, [(position, company)], CUTOFF)
    return result, result["positions"][0]


def test_missing_market_value_base_is_not_zero_contribution(db):
    result, entry = _entry(db, with_ledger_gap=False)
    # Antes: end_value=0.0 -> contribution = -1200 (perdida inventada)
    assert entry["end_value"] is None
    assert entry["contribution_pnl"] is None
    assert result["total_pnl"] is None


def test_missing_market_value_base_in_unreconciled_path_is_none(db):
    _, entry = _entry(db, with_ledger_gap=True)
    assert entry["end_value"] is None


def test_start_value_is_none_when_not_computable(db):
    _usd_base(db)
    company = _company(db)
    position = _position(db, company, qty=10, price=150)
    _tx(db, company, "buy", 10, 100, date(2025, 6, 1))  # sin precio previo
    entry = PortfolioIntelligenceService()._ledger_contribution(
        db, [(position, company)], CUTOFF
    )["positions"][0]
    assert entry["reason"] == "missing_start_price"
    assert entry["start_value"] is None  # antes: 0.0
