"""El puente relajado no resta caja en otra divisa de la deuda."""
from app.valuation.financial_snapshot import FinancialSnapshotBuilder
from tests.test_tesis_huecos_puente import _anchor, _company, _fact, db  # noqa: F401


def test_cross_source_cash_in_another_currency_is_not_subtracted(db):
    company = _company(db, ticker="BRGCUR", currency="USD")
    _anchor(db, company, source="SEC", unit="USD", period="2026-06-30:Q2")
    _fact(db, company, "shares_diluted", 100, "2026-06-30:Q2", source="SEC", unit="shares", quarter="Q2")
    _fact(db, company, "total_debt", 200, "2025-12-31:FY", source="YAHOO_FUNDAMENTALS", unit="USD")
    _fact(db, company, "cash_and_equivalents", 100, "2025-12-31:FY", source="SEC", unit="EUR")
    snapshot = FinancialSnapshotBuilder().build(db, company)
    assert "net_debt" not in snapshot.facts
    assert "net_debt" in snapshot.missing_inputs
