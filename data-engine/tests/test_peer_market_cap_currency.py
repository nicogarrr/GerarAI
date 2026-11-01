"""Comparables: el tamaño se compara en la misma divisa.

El market cap derivado se guarda en la divisa de la empresa (JPY, EUR, GBX...)
y el de Finnhub en USD. La seleccion de peers dividia los valores tal cual:
Toyota (45 billones de JPY ~ 300.000 M USD) salia 150 veces mayor que una
empresa de 300.000 M USD y perdia la dimension de tamaño.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.models.entities import FinancialFact, FXRate
from app.services.peer_comparison_service import PeerComparisonService
from tests.test_peer_selection_query_count import _session


def _set_cap(db, company_id, value, unit):
    db.query(FinancialFact).filter(FinancialFact.company_id == company_id).delete()
    db.add(FinancialFact(
        tenant_id=1, company_id=company_id, metric="market_cap", period="FY2024",
        fiscal_year=2024, value=Decimal(value), unit=unit, source_type="test",
    ))


def _candidate_row(trace, ticker):
    return next(row for row in trace["candidates"] if row["ticker"] == ticker)


def test_market_cap_en_otra_divisa_se_pasa_a_usd():
    _engine, db, companies = _session(2)
    target, toyota = companies
    _set_cap(db, target.id, "300000000000", "USD")
    _set_cap(db, toyota.id, "45000000000000", "JPY")
    # 1 JPY = 1/150 USD (quote x rate = base).
    db.add(FXRate(base_currency="USD", quote_currency="JPY", rate=Decimal("0.0066666667"),
                  rate_date=date.today(), source="test", tenant_id=1))
    db.commit()
    _peers, _basis, trace = PeerComparisonService()._find_peers(db, target, limit=8)
    row = _candidate_row(trace, toyota.ticker)
    # Mismo tamaño (ratio 1,00x): 0,9, el maximo de la escala (antes 0: 150x).
    assert row["dimensions"]["market_cap"] == 0.9


def test_market_cap_sin_tipo_de_cambio_no_puntua_tamano():
    _engine, db, companies = _session(2)
    target, other = companies
    _set_cap(db, target.id, "300000000000", "USD")
    _set_cap(db, other.id, "300000000000", "JPY")
    db.commit()
    _peers, _basis, trace = PeerComparisonService()._find_peers(db, target, limit=8)
    row = _candidate_row(trace, other.ticker)
    # 300.000 M JPY no son 300.000 M USD: sin tipo, sin dimension de tamaño.
    assert "market_cap" not in row["dimensions"]

